::copy "C:\My Stuff\1.mp4" "C:\Program Files (x86)\Steam\steamapps\common\movie\1.mp4"
cd C:\Program Files (x86)\Steam\steamapps\common\movie
for %%i in (*.mp4) do @echo file '%%i' >> mylist.txt
"C:\Code\ffmpeg\bin\ffmpeg.exe" -f concat -safe 0 -i mylist.txt -c copy merged_video.mp4


for /f "tokens=1-4 delims=/- " %%a in ('date /t') do set datestr=%%a-%%b-%%c
for /f "tokens=1-2 delims=:. " %%a in ('time /t') do set timestr=%%a-%%b

copy merged_video.mp4 "C:\Users\rajes\Videos\Dota 2\merged_video_%datestr%_%timestr%.mp4"
start "" "C:\Users\rajes\Videos\Dota 2"


::"C:\Code\ffmpeg\bin\ffmpeg.exe" -i merged_video.mp4 -c:v hevc_nvenc -preset fast -b:v 15M -c:a copy "C:\Users\rajes\Videos\Dota 2\compressed_video_%datestr%_%timestr%.mp4"
::"C:\Code\ffmpeg\bin\ffmpeg.exe" -i merged_video.mp4 -c:v h264_nvenc -preset fast -b:v 12M -c:a aac -b:a 192k "C:\Users\rajes\Videos\Dota 2\compressed_video_%datestr%_%timestr%.mp4"
::"C:\Code\ffmpeg\bin\ffmpeg.exe" -i merged_video.mp4 -preset ultrafast -crf 23 -c:v libx264  "C:\Users\rajes\Videos\Dota 2\compressed_video_%datestr%_%timestr%.mp4"

::MOVE merged_video.mp4 "C:\Users\rajes\Videos\Dota 2\compressed_video_%datestr%_%timestr%.mp4"


del mylist.txt
del merged_video.mp4
mkdir Archive\%datestr%_%timestr%

move *.* "C:\Program Files (x86)\Steam\steamapps\common\movie\Archive\%datestr%_%timestr%"
cd C:\Users\rajes\OneDrive\Desktop
start "" "C:\Users\rajes\Videos\Dota 2"

pause
