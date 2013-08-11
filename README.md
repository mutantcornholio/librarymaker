A python script for linux (for now), that organizes your library in tags, using symlinks.
Tags are fetched from last.fm
You need to store your folders named as asrtist names in WATCH_DIR directory.
Script adds tag names folders in DEST_DIR and places symlinks in those. 
There is also tag blacklist, so you will not have 'electronic' tag, with 9000 artist in (unless you want to).
For example:
watch dir:
-65daysofstatic
-Aphex Twin
-Crystal Castles
-God Is An Astronaut
dest dir:
-ambient
--Aphex Twin
--God Is An Astronaut
-chiptune
--Crystal Castles
-idm
--Aphex Twin
-post-rock
--65daysofstatic
--God Is An Astronaut
