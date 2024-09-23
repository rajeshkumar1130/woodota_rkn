import json
from enum import Enum
from pathlib import PosixPath
from functools import cached_property
from typing import List, Dict, Optional

import numpy as np
import pandas as pd
from loguru import logger

from settings import MERGE_GAP, REPLAY_DIR, DHP_SMOOTH_WINDOW, MAX_HP_WINDOW
from utils import TimeSeries, TimeTable, merge_close_intervals, convert_to_dota_clock_format
from attacks import find_attacks


class NotParsedError(Exception):
    pass


class Match:
    """Dota 2 match metadata and events from replay"""

    def __init__(self, match_id: int, jsonlines_path: PosixPath | str):
        self.match_id = match_id
        self.jsonlines_path = jsonlines_path
        self._events = None
        self.unit_to_slot = None
        self.slot_to_unit = None
        self.name_to_slot = None
        self.slot_to_name = None
        self.steam_ids = None
        self._players = None

    def __str__(self) -> str:
        parsed = self._events is not None
        return f'Match: {self.match_id}, parsed: {parsed}'

    def __repr__(self) -> str:
        return self.__str__()

    @classmethod
    def from_id(cls: 'Match', match_id: int) -> 'Match':
        path = PosixPath(REPLAY_DIR)
        filename = f'{match_id}.jsonlines'
        path = path / filename

        try:
            match_id = int(match_id)
        except ValueError:
            raise NotParsedError(f"Can't extract match_id from file: {filename}")

        if not path.exists():
            raise NotParsedError(f"Can't find the file {path}. Did you forget to parse the match?")

        match = cls(match_id, path)
        return match

    @cached_property
    def events(self) -> List[Dict]:
        self.parse()
        return self._events

    @cached_property
    def players(self) -> List:
        if self._players is None:
            self.parse()
        return self._players

    def parse(self) -> None:
        """
        Load events from the parsed replay.

        Note: Memory Intensive!
        """
        if self._events is not None:
            return self._events

        events = []
        unit_to_slot = dict()
        epilogue = None
        with open(self.jsonlines_path, 'r') as fin:
            for line in fin:
                e = json.loads(line)
                if 'time' not in e:
                    raise NotParsedError(f"The event doesn't contain a time: {e}")

                events.append(e)

                if e['type'] == 'interval' and e.get('unit'):
                    unit_to_slot[e['unit']] = e['slot']

                if e['type'] == 'epilogue':
                    epilogue = e

        if not events:
            raise NotParsedError(f'Events list is empty for: {self.jsonlines_path}')

        self._events = events
        self.unit_to_slot = unit_to_slot
        self.slot_to_unit = {slot: name for name, slot in self.unit_to_slot.items()}
        self.name_to_slot = {UnitToName[unit].value: slot for unit, slot in unit_to_slot.items()}
        self.slot_to_name = {slot: name for name, slot in self.name_to_slot.items()}
        self.steam_ids = self._get_steam_ids_from_epilogue(epilogue)
        self._players = self._construct_players()

    def _get_steam_ids_from_epilogue(self, epilogue: Dict) -> List[int]:
        epilogue = json.loads(epilogue['key'])
        game_info = epilogue['gameInfo_']
        dota_info = game_info['dota_']
        players_info = dota_info['playerInfo_']
        steam_ids = [p['steamid_'] for p in players_info]
        return steam_ids

    def _construct_players(self) -> List['MatchPlayer']:
        players = []
        for slot, hero_name, steam_id in zip(self.slot_to_name.keys(), self.name_to_slot.keys(), self.steam_ids):
            player = MatchPlayer(self, slot, hero_name, steam_id)
            players.append(player)
        return players

    def get_player(self, hero_name: str) -> Optional['MatchPlayer']:
        if self.players is None:
            raise NotParsedError(f"Match {self.match_id} has no players")

        for player in self.players:
            if player.hero_name == hero_name:
                return player
        else:
            return None

    @cached_property
    def action_moments(self) -> TimeTable:
        moments = []
        for player in self.players:
            moments.append(player.action_moments)
        df_moments = pd.concat(moments)
        moments = df_moments[['start', 'end']].to_dict('records')
        moments = merge_close_intervals(moments, MERGE_GAP)
        df_moments = TimeTable(moments)
        df_moments['time'] = df_moments['start']
        return df_moments

    def get_action_moments(self) -> List[Dict]:
        """Time intervals in Dota 2 time format where the player escaped attack on it or participated in a kill"""
        moments = self.action_moments
        moments = moments[['start', 'end']]
        moments = moments.to_dict('records')

        for moment in moments:
            moment['clock_start'] = convert_to_dota_clock_format(moment['start'])
            moment['clock_end'] = convert_to_dota_clock_format(moment['end'])
        return moments
    
    def single_player_action_moments(self, hero_name: str) -> TimeTable:
        moments = []
        for player in self.players:
            if player.hero_name == hero_name:
                moments.append(player.action_moments)
        df_moments = pd.concat(moments)
        moments = df_moments[['start', 'end']].to_dict('records')
        moments = merge_close_intervals(moments, 10)
        df_moments = TimeTable(moments)
        df_moments['time'] = df_moments['start']
        return df_moments
    
    def get_single_player_action_moments(self, hero_name: str) -> List[Dict]:
        """Time intervals in Dota 2 time format where the player escaped attack on it or participated in a kill"""
        moments = self.single_player_action_moments(hero_name)
        moments = moments[['start', 'end']]
        moments = moments.to_dict('records')

        for moment in moments:
            moment['clock_start'] = convert_to_dota_clock_format(moment['start'])
            moment['clock_end'] = convert_to_dota_clock_format(moment['end'])
        return moments


class MatchPlayer:
    """Dota 2 match participant"""

    def __init__(self, match: Match, slot: int, hero_name: str, steam_id: int = None):
        self.match = match
        self.slot = slot
        self.hero_name = hero_name
        self.steam_id = steam_id
        self.unit = match.slot_to_unit[slot]

    def __str__(self) -> str:
        match_id = self.match.match_id
        slot = self.slot
        hero_name = self.hero_name
        steam_id = self.steam_id
        return f'MatchPlayer at match: {match_id}, slot: {slot}, hero_name: {hero_name}, steam_id: {steam_id}'

    def __repr__(self) -> str:
        return self.__str__()

    @cached_property
    def events(self) -> List[Dict]:
        return self.match.events

    @cached_property
    def hp(self) -> TimeSeries:
        time = []
        health = []
        for e in self.events:
            try:
                if e['type'] == 'interval' and e.get('unit', 'unknown_unit') == self.unit:
                    time.append(e['ticks'])
                    health.append(e['hp'])
            except Exception as e:
                logger.error(e)
                break
        series = TimeSeries(index=time, data=health, name='hp')
        return series

    @cached_property
    def max_hp(self) -> TimeSeries:
        series = self.hp.rolling(MAX_HP_WINDOW).max()
        series = series.fillna(method='bfill')
        return TimeSeries(series)

    @cached_property
    def deaths(self) -> TimeSeries:
        events = []
        for e in self.events:
            if (
                e['type'] == 'DOTA_COMBATLOG_DEATH' and
                e['targetsourcename'] == self.hero_name and
                e['targethero'] and
                not e['targetillusion']
            ):
                events.append(e)
        df = TimeTable(events)
        return df

    @cached_property
    def hero_damage_in(self) -> TimeTable:
        events = []
        for e in self.events:
            if (
                e['type'] == 'DOTA_COMBATLOG_DAMAGE' and
                e['targetsourcename'] == self.hero_name and
                e['targethero'] and
                not e['targetillusion'] and
                (e['attackerhero'] or e['attackerillusion'])
            ):
                events.append(e)
        df = TimeTable(events)
        return df

    @cached_property
    def hero_damage_out(self) -> TimeTable:
        events = []
        for e in self.events:
            if (
                e['type'] == 'DOTA_COMBATLOG_DAMAGE' and
                e['sourcename'] == self.hero_name and
                e['targethero'] and
                not e['targetillusion']
            ):
                events.append(e)
        df = TimeTable(events)
        return df

    @cached_property
    def dhp(self) -> TimeSeries:
        """
        Discrete difference of player hp

        hp[i + 1] - hp[i]
        """
        discrete_difference = np.diff(self.hp)
        discrete_difference = np.append(np.nan, discrete_difference)
        series = TimeSeries(index=self.hp.index, data=discrete_difference, name='dhp')
        series.fillna(method='bfill', inplace=True)
        return series

    @cached_property
    def sdhp(self) -> TimeSeries:
        """Smooth discrete difference of player hp"""
        moving_average = self.dhp.rolling(DHP_SMOOTH_WINDOW).mean()
        moving_average = moving_average.fillna(method='bfill')
        series = TimeSeries(index=self.dhp.index, data=moving_average, name='sdhp')
        return series

    @cached_property
    def as_target(self) -> TimeTable:
        """Time intervals where the player was attacked but not necessarily killed"""
        intervals = find_attacks(self)
        df = TimeTable(intervals)
        if df.size == 0:
            return df
        df['time'] = df['start']
        df['target'] = self
        return df

    @cached_property
    def as_attacker(self) -> TimeTable:
        """Time intervals where the player attacked other players"""
        intervals = []
        for player in self.match.players:
            for _, interval in player.as_target.iterrows():
                attackers = interval['attacker_heroes']
                if self in attackers:
                    intervals.append(interval)
        intervals.sort(key=lambda dct: dct['start'])
        df = TimeTable(intervals)
        if df.size == 0:
            return df
        df['time'] = df['start']
        return df

    @cached_property
    def action_moments(self) -> TimeTable:
        """Time intervals where the player escaped attack on it or participated in a kill"""
        df_escapes = self.as_target
        if not df_escapes.empty:
            df_escapes = df_escapes[(~df_escapes['target_dead']) & df_escapes['attacker_heroes']]
        df_attacks = self.as_attacker
        if not df_attacks.empty:
            df_attacks = df_attacks[df_attacks['target_dead']]
        """"df_moments = pd.concat([df_escapes, df_attacks])"""
        df_moments = df_attacks

        if df_moments.empty:
            return TimeTable([])

        moments = df_moments[['start', 'end']].to_dict('records')
        moments = merge_close_intervals(moments, MERGE_GAP)
        df_moments = TimeTable(moments)
        df_moments['time'] = df_moments['start']
        return df_moments


class UnitToName(str, Enum):
    """
    Converts interval unit field to combatlog name with respect to OpenDota rules
    https://raw.githubusercontent.com/odota/dotaconstants/master/build/hero_names.json
    https://raw.githubusercontent.com/SteamDatabase/GameTracking-Dota2/master/game/dota/bin/linuxsteamrt64/libserver_strings.txt
    """
    CDOTA_Unit_Hero_Abaddon = 'npc_dota_hero_abaddon'
    CDOTA_Unit_Hero_AbyssalUnderlord = 'npc_dota_hero_abyssal_underlord'
    CDOTA_Unit_Hero_Alchemist = 'npc_dota_hero_alchemist'
    CDOTA_Unit_Hero_AncientApparition = 'npc_dota_hero_ancient_apparition'
    CDOTA_Unit_Hero_AntiMage = 'npc_dota_hero_antimage'
    CDOTA_Unit_Hero_ArcWarden = 'npc_dota_hero_arc_warden'
    CDOTA_Unit_Hero_Axe = 'npc_dota_hero_axe'
    CDOTA_Unit_Hero_Bane = 'npc_dota_hero_bane'
    CDOTA_Unit_Hero_Batrider = 'npc_dota_hero_batrider'
    CDOTA_Unit_Hero_Beastmaster = 'npc_dota_hero_beastmaster'
    CDOTA_Unit_Hero_Bloodseeker = 'npc_dota_hero_bloodseeker'
    CDOTA_Unit_Hero_BountyHunter = 'npc_dota_hero_bounty_hunter'
    CDOTA_Unit_Hero_Brewmaster = 'npc_dota_hero_brewmaster'
    CDOTA_Unit_Hero_Bristleback = 'npc_dota_hero_bristleback'
    CDOTA_Unit_Hero_Broodmother = 'npc_dota_hero_broodmother'
    CDOTA_Unit_Hero_Centaur = 'npc_dota_hero_centaur'
    CDOTA_Unit_Hero_ChaosKnight = 'npc_dota_hero_chaos_knight'
    CDOTA_Unit_Hero_Chen = 'npc_dota_hero_chen'
    CDOTA_Unit_Hero_Clinkz = 'npc_dota_hero_clinkz'
    CDOTA_Unit_Hero_CrystalMaiden = 'npc_dota_hero_crystal_maiden'
    CDOTA_Unit_Hero_DarkSeer = 'npc_dota_hero_dark_seer'
    CDOTA_Unit_Hero_DarkWillow = 'npc_dota_hero_dark_willow'
    CDOTA_Unit_Hero_Dawnbreaker = 'npc_dota_hero_dawnbreaker'
    CDOTA_Unit_Hero_Dazzle = 'npc_dota_hero_dazzle'
    CDOTA_Unit_Hero_DeathProphet = 'npc_dota_hero_death_prophet'
    CDOTA_Unit_Hero_Disruptor = 'npc_dota_hero_disruptor'
    CDOTA_Unit_Hero_DoomBringer = 'npc_dota_hero_doom_bringer'
    CDOTA_Unit_Hero_DragonKnight = 'npc_dota_hero_dragon_knight'
    CDOTA_Unit_Hero_DrowRanger = 'npc_dota_hero_drow_ranger'
    CDOTA_Unit_Hero_EarthSpirit = 'npc_dota_hero_earth_spirit'
    CDOTA_Unit_Hero_Earthshaker = 'npc_dota_hero_earthshaker'
    CDOTA_Unit_Hero_Elder_Titan = 'npc_dota_hero_elder_titan'
    CDOTA_Unit_Hero_EmberSpirit = 'npc_dota_hero_ember_spirit'
    CDOTA_Unit_Hero_Enchantress = 'npc_dota_hero_enchantress'
    CDOTA_Unit_Hero_Enigma = 'npc_dota_hero_enigma'
    CDOTA_Unit_Hero_FacelessVoid = 'npc_dota_hero_faceless_void'
    CDOTA_Unit_Hero_Furion = 'npc_dota_hero_furion'
    CDOTA_Unit_Hero_Grimstroke = 'npc_dota_hero_grimstroke'
    CDOTA_Unit_Hero_Gyrocopter = 'npc_dota_hero_gyrocopter'
    CDOTA_Unit_Hero_Hoodwink = 'npc_dota_hero_hoodwink'
    CDOTA_Unit_Hero_Huskar = 'npc_dota_hero_huskar'
    CDOTA_Unit_Hero_Invoker = 'npc_dota_hero_invoker'
    CDOTA_Unit_Hero_Jakiro = 'npc_dota_hero_jakiro'
    CDOTA_Unit_Hero_Juggernaut = 'npc_dota_hero_juggernaut'
    CDOTA_Unit_Hero_KeeperOfTheLight = 'npc_dota_hero_keeper_of_the_light'
    CDOTA_Unit_Hero_Kunkka = 'npc_dota_hero_kunkka'
    CDOTA_Unit_Hero_Legion_Commander = 'npc_dota_hero_legion_commander'
    CDOTA_Unit_Hero_Leshrac = 'npc_dota_hero_leshrac'
    CDOTA_Unit_Hero_Lich = 'npc_dota_hero_lich'
    CDOTA_Unit_Hero_Life_Stealer = 'npc_dota_hero_life_stealer'
    CDOTA_Unit_Hero_Lina = 'npc_dota_hero_lina'
    CDOTA_Unit_Hero_Lion = 'npc_dota_hero_lion'
    CDOTA_Unit_Hero_LoneDruid = 'npc_dota_hero_lone_druid'
    CDOTA_Unit_Hero_Luna = 'npc_dota_hero_luna'
    CDOTA_Unit_Hero_Lycan = 'npc_dota_hero_lycan'
    CDOTA_Unit_Hero_Magnataur = 'npc_dota_hero_magnataur'
    CDOTA_Unit_Hero_Marci = 'npc_dota_hero_marci'
    CDOTA_Unit_Hero_Mars = 'npc_dota_hero_mars'
    CDOTA_Unit_Hero_Medusa = 'npc_dota_hero_medusa'
    CDOTA_Unit_Hero_Meepo = 'npc_dota_hero_meepo'
    CDOTA_Unit_Hero_Mirana = 'npc_dota_hero_mirana'
    CDOTA_Unit_Hero_MonkeyKing = 'npc_dota_hero_monkey_king'
    CDOTA_Unit_Hero_Morphling = 'npc_dota_hero_morphling'
    CDOTA_Unit_Hero_Naga_Siren = 'npc_dota_hero_naga_siren'
    CDOTA_Unit_Hero_Necrolyte = 'npc_dota_hero_necrolyte'
    CDOTA_Unit_Hero_Nevermore = 'npc_dota_hero_nevermore'
    CDOTA_Unit_Hero_NightStalker = 'npc_dota_hero_night_stalker'
    CDOTA_Unit_Hero_Nyx_Assassin = 'npc_dota_hero_nyx_assassin'
    CDOTA_Unit_Hero_Obsidian_Destroyer = 'npc_dota_hero_obsidian_destroyer'
    CDOTA_Unit_Hero_Ogre_Magi = 'npc_dota_hero_ogre_magi'
    CDOTA_Unit_Hero_Omniknight = 'npc_dota_hero_omniknight'
    CDOTA_Unit_Hero_Oracle = 'npc_dota_hero_oracle'
    CDOTA_Unit_Hero_Pangolier = 'npc_dota_hero_pangolier'
    CDOTA_Unit_Hero_PhantomAssassin = 'npc_dota_hero_phantom_assassin'
    CDOTA_Unit_Hero_PhantomLancer = 'npc_dota_hero_phantom_lancer'
    CDOTA_Unit_Hero_Phoenix = 'npc_dota_hero_phoenix'
    CDOTA_Unit_Hero_PrimalBeast = 'npc_dota_hero_primal_beast'
    CDOTA_Unit_Hero_Puck = 'npc_dota_hero_puck'
    CDOTA_Unit_Hero_Pudge = 'npc_dota_hero_pudge'
    CDOTA_Unit_Hero_Pugna = 'npc_dota_hero_pugna'
    CDOTA_Unit_Hero_QueenOfPain = 'npc_dota_hero_queenofpain'
    CDOTA_Unit_Hero_Rattletrap = 'npc_dota_hero_rattletrap'
    CDOTA_Unit_Hero_Razor = 'npc_dota_hero_razor'
    CDOTA_Unit_Hero_Riki = 'npc_dota_hero_riki'
    CDOTA_Unit_Hero_Rubick = 'npc_dota_hero_rubick'
    CDOTA_Unit_Hero_SandKing = 'npc_dota_hero_sand_king'
    CDOTA_Unit_Hero_ShadowShaman = 'npc_dota_hero_shadow_shaman'
    CDOTA_Unit_Hero_Shadow_Demon = 'npc_dota_hero_shadow_demon'
    CDOTA_Unit_Hero_Shredder = 'npc_dota_hero_shredder'
    CDOTA_Unit_Hero_Silencer = 'npc_dota_hero_silencer'
    CDOTA_Unit_Hero_SkeletonKing = 'npc_dota_hero_skeleton_king'
    CDOTA_Unit_Hero_Skywrath_Mage = 'npc_dota_hero_skywrath_mage'
    CDOTA_Unit_Hero_Slardar = 'npc_dota_hero_slardar'
    CDOTA_Unit_Hero_Slark = 'npc_dota_hero_slark'
    CDOTA_Unit_Hero_Snapfire = 'npc_dota_hero_snapfire'
    CDOTA_Unit_Hero_Sniper = 'npc_dota_hero_sniper'
    CDOTA_Unit_Hero_Spectre = 'npc_dota_hero_spectre'
    CDOTA_Unit_Hero_SpiritBreaker = 'npc_dota_hero_spirit_breaker'
    CDOTA_Unit_Hero_StormSpirit = 'npc_dota_hero_storm_spirit'
    CDOTA_Unit_Hero_Sven = 'npc_dota_hero_sven'
    CDOTA_Unit_Hero_Techies = 'npc_dota_hero_techies'
    CDOTA_Unit_Hero_TemplarAssassin = 'npc_dota_hero_templar_assassin'
    CDOTA_Unit_Hero_Terrorblade = 'npc_dota_hero_terrorblade'
    CDOTA_Unit_Hero_Tidehunter = 'npc_dota_hero_tidehunter'
    CDOTA_Unit_Hero_Tinker = 'npc_dota_hero_tinker'
    CDOTA_Unit_Hero_Tiny = 'npc_dota_hero_tiny'
    CDOTA_Unit_Hero_Treant = 'npc_dota_hero_treant'
    CDOTA_Unit_Hero_TrollWarlord = 'npc_dota_hero_troll_warlord'
    CDOTA_Unit_Hero_Tusk = 'npc_dota_hero_tusk'
    CDOTA_Unit_Hero_Undying = 'npc_dota_hero_undying'
    CDOTA_Unit_Hero_Ursa = 'npc_dota_hero_ursa'
    CDOTA_Unit_Hero_VengefulSpirit = 'npc_dota_hero_vengefulspirit'
    CDOTA_Unit_Hero_Venomancer = 'npc_dota_hero_venomancer'
    CDOTA_Unit_Hero_Viper = 'npc_dota_hero_viper'
    CDOTA_Unit_Hero_Visage = 'npc_dota_hero_visage'
    CDOTA_Unit_Hero_Void_Spirit = 'npc_dota_hero_void_spirit'
    CDOTA_Unit_Hero_Warlock = 'npc_dota_hero_warlock'
    CDOTA_Unit_Hero_Weaver = 'npc_dota_hero_weaver'
    CDOTA_Unit_Hero_Windrunner = 'npc_dota_hero_windrunner'
    CDOTA_Unit_Hero_Winter_Wyvern = 'npc_dota_hero_winter_wyvern'
    CDOTA_Unit_Hero_Wisp = 'npc_dota_hero_wisp'
    CDOTA_Unit_Hero_WitchDoctor = 'npc_dota_hero_witch_doctor'
    CDOTA_Unit_Hero_Zuus = 'npc_dota_hero_zuus'
    CDOTA_Unit_Hero_Muerta = 'npc_dota_hero_muerta'
    CDOTA_Unit_Hero_Ringmaster = 'npc_dota_hero_ringmaster'


