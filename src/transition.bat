setlocal enabledelayedexpansion

:: Set transition duration
set duration=1
cd C:\Program Files (x86)\Steam\steamapps\common\movie
for %%i in (*.mp4) do @echo "%%i" >> videos.txt
:: Set the input video list (videos.txt created earlier)
set "input_list=videos.txt"

:: Create the FFmpeg filter_complex string
set "filter_complex="
set "audio_filter="
set /a offset=0
set /a index=0

:: Read the videos from the list and construct the filter and file list
for /f "tokens=*" %%A in (%input_list%) do (
    set "filelist=!filelist! -i %%A"
    set "videos[!index!]=%%A"
    set /a index+=1
)

:: Ensure there are at least two videos
if %index% LSS 2 (
    echo Not enough videos to merge. At least two are required.
    exit /b
)

:: Construct the filter_complex string for video & audio transitions
for /l %%i in (1,1,%index%) do (
	set  /a abc =  %%i-1
	echo abc = !abc!
    for /f %%D in ('ffprobe -i "!videos[!abc!]!" -show_entries format=duration -v quiet -of csv^=p^=0') do set "prev_duration=%%D"
    set /a offset=!offset! + !prev_duration! - %duration%
    set "filter_complex=!filter_complex![v!abc!][%%i:v]xfade=transition=fade:duration=%duration%:offset=!offset![v%%i];"
    set "audio_filter=!audio_filter![a!abc!][%%i:a]acrossfade=d=%duration%[a%%i];"
)

:: Trim the last semicolon (trailing garbage issue)
set "audio_filter=!audio_filter:~0,-1!"
echo ffmpeg %filelist% -filter_complex "!filter_complex! !audio_filter!" -map "[v%index%]" -map "[a%index%]" -c:v libx264 -crf 23 -preset fast output.mp4

:: Run FFmpeg to merge the videos with the transition
ffmpeg %filelist% -filter_complex "!filter_complex! !audio_filter!" -map "[v%index%]" -map "[a%index%]" -c:v libx264 -crf 23 -preset fast output.mp4

del videos.txt


echo Merge complete! Output saved as output.mp4
pause
