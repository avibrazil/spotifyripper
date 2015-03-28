#!/usr/bin/env python
# -*- coding: utf8 -*-

from subprocess import call, Popen, PIPE
from spotify import Link, Image
from jukebox import Jukebox, container_loaded
import os, sys
import threading
import time

reload(sys)  
sys.setdefaultencoding('utf8')


playback = False # set if you want to listen to the tracks that are currently ripped (start with "padsp ./jbripper.py ..." if using pulse audio)
wav = False # also saves a .pcm file with the raw PCM data as delivered by libspotify ()
fileNameMaxSize=255 # your filesystem's maximum filename size. Linux' Ext4 is 255. filename/filename/filename 

pcmfile = None
pipe = None
ripping = False
size = 0
end_of_track = threading.Event()

def printstr(str): # print without newline
    sys.stdout.write(str)
    sys.stdout.flush()


def transliterate(str):
    transliterated=str
    transliterated=transliterated.replace('/',u'／')
    transliterated=transliterated.replace('*',u'✱')
    transliterated=transliterated.replace('#',u'♯')
    transliterated=transliterated.replace(':',u'∶')
    transliterated=transliterated.replace('?',u'⁇')
    transliterated=transliterated.replace('\\',u'＼')
    transliterated=transliterated.replace('|',u'￨')
    transliterated=transliterated.replace('>',u'＞')
    transliterated=transliterated.replace('<',u'＜')
    transliterated=transliterated.replace('&',u'＆')    
    return transliterated


def unicode_truncate(s, length, encoding='utf-8'):
    encoded = s.encode(encoding)[:length]
    return encoded.decode(encoding, 'ignore')

def track_path(track):
    global fileNameMaxSize
	
    oalbum=track.album()
    num_track = track.index()
    year=oalbum.year()
    album_artist=transliterate(oalbum.artist().name())
    track_artist=transliterate(u' • '.join([str(x.name()) for x in track.artists()]))
    track_name=transliterate(track.name())
    album_name=transliterate(oalbum.name())
    
    if (album_artist == track_artist):
        track_file="{:02d} {}".format(num_track, track_name)
    else:
        track_file="{:02d} {} ♫ {}".format(num_track, track_artist, track_name)
    
    return "{aartist}/{year:04d} • {album}/{file}".format(year=year,
        aartist = unicode_truncate(album_artist, fileNameMaxSize),
        album   = unicode_truncate(album_name,   fileNameMaxSize-4-2-3),
        file    = unicode_truncate(track_file,   fileNameMaxSize-4))


def rip_init(session, track):
    global pipe, ripping, wpipe, size

    size = 0
    file_prefix = track_path(track)
    mp3file = file_prefix+".mp3"
    directory = os.path.dirname(file_prefix)
    
    if not os.path.exists(directory):
        os.makedirs(directory)
    printstr("ripping " + file_prefix + ".mp3 ...\n")
    p = Popen(["lame", "--silent", "-V0", "-m", "s", "-h", "-r", "-", file_prefix + ".mp3"], stdin=PIPE)
    pipe = p.stdin
    if wav:
      w=Popen(["ffmpeg",
      		"-loglevel", "quiet",
      		"-f", "s16le",
      		"-ar", "44100",
      		"-ac", "2",
      		"-i", "-",
      		file_prefix + ".wav"],
      	stdin=PIPE)
      wpipe=w.stdin
    ripping = True


def rip_terminate(session, track):
    global ripping, pipe, pcmfile, rawpcm
    if pipe is not None:
        print('\ndone!')
        pipe.close()
    if wav:
        wpipe.close()
    ripping = False

def rip(session, frames, frame_size, num_frames, sample_type, sample_rate, channels):
    global size
    printstr('.')
    if ripping:
        pipe.write(frames);
#        printstr("     " + size + " bytes\r")
        if wav:
          wpipe.write(frames)

def rip_id3(session, track): # write ID3 data
    file_prefix = track_path(track)
    mp3file = file_prefix+".mp3"
    directory = os.path.dirname(file_prefix)

    # download cover
    image = session.image_create(track.album().cover())
    while not image.is_loaded(): # does not work from MainThread!
        time.sleep(0.1)
    fh_cover = open(directory + '/folder.jpg','wb')
    fh_cover.write(image.data())
    fh_cover.close()


    oalbum=track.album()
    num_track = str("%02d" % (track.index(),))
    year=str(oalbum.year())
    album_artist=transliterate(oalbum.artist().name())
    track_artist=u' • '.join([str(x.name()) for x in track.artists()])
    track_name=track.name()
    album_name=oalbum.name()
    
#    spotify_link="This track on Spotify is {}".format(track.link())

    # write id3 data
    call(["eyeD3",
          "--add-image", directory + "/folder.jpg:FRONT_COVER",
          "-t", track_name,
          "-a", track_artist,
          "-b", album_artist,
 #         "-c", spotify_link,
          "-A", album_name,
          "-n", num_track,
          "-Y", year,
          "--to-v2.3",
          "-Q",
          mp3file
    ])

    # delete cover
    # call(["rm", "-f", "folder.jpg"])

class RipperThread(threading.Thread):
    def __init__(self, ripper):
        threading.Thread.__init__(self)
        self.ripper = ripper

    def run(self):
        # wait for container
        container_loaded.wait()
        container_loaded.clear()

        # create track iterator
        link = Link.from_string(sys.argv[3])
        if link.type() == Link.LINK_TRACK:
            track = link.as_track()
            itrack = iter([track])
        elif link.type() == Link.LINK_PLAYLIST:
            playlist = link.as_playlist()
            print('loading playlist ...')
            while not playlist.is_loaded():
                time.sleep(0.1)
            print('done')
            itrack = iter(playlist)

        # ripping loop
        session = self.ripper.session
        for track in itrack:

                self.ripper.load_track(track)

                rip_init(session, track)

                self.ripper.play()

                end_of_track.wait()
                end_of_track.clear() # TODO check if necessary

                rip_terminate(session, track)
                rip_id3(session, track)

        self.ripper.disconnect()

class Ripper(Jukebox):
    def __init__(self, *a, **kw):
        Jukebox.__init__(self, *a, **kw)
        self.ui = RipperThread(self) # replace JukeboxUI
        self.session.set_preferred_bitrate(1) # 320 bps

    def music_delivery_safe(self, session, frames, frame_size, num_frames, sample_type, sample_rate, channels):
        rip(session, frames, frame_size, num_frames, sample_type, sample_rate, channels)
        if playback:
            return Jukebox.music_delivery_safe(self, session, frames, frame_size, num_frames, sample_type, sample_rate, channels)
        else:
            return num_frames

    def end_of_track(self, session):
        Jukebox.end_of_track(self, session)
        end_of_track.set()


if __name__ == '__main__':
	if len(sys.argv) >= 3:
		ripper = Ripper(sys.argv[1],sys.argv[2]) # login
		ripper.connect()
	else:
		print "usage : \n"
		print "	  ./jbripper.py [username] [password] [spotify_url]"
		print "example : \n"
	 	print "   ./jbripper.py user pass spotify:track:52xaypL0Kjzk0ngwv3oBPR - for a single file"
		print "   ./jbripper.py user pass spotify:user:username:playlist:4vkGNcsS8lRXj4q945NIA4 - rips entire playlist"
