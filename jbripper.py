#!/usr/bin/env python
# -*- coding: utf8 -*-

from subprocess import call, Popen, PIPE
from spotify import Link, Image
from jukebox import Jukebox, container_loaded
import os, sys
import threading
import time
import pprint
from eyed3 import id3
import eyed3

reload(sys)  
sys.setdefaultencoding('utf8')


playback = False # set if you want to listen to the tracks that are currently ripped (start with "padsp ./jbripper.py ..." if using pulse audio)
wav = False # also saves a .pcm file with the raw PCM data as delivered by libspotify ()
m4a = False
mp3 = True
fileNameMaxSize=255 # your filesystem's maximum filename size. Linux' Ext4 is 255. filename/filename/filename 
defaultgenre = u'☣ UNKNOWN ♺'

pcmfile = None
pipe = None
ripping = False
size = 0
feedbackchar = "-"
feedbackcharDelay = 0
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


# Setup all pipes
def rip_init(session, track):
    global pipe, ripping, wpipe, size, defaultgenre

    size = 0
    file_prefix = track_path(track)
    directory = os.path.dirname(file_prefix)
    
    if not os.path.exists(directory):
        os.makedirs(directory)


    pipe = []
    
    if m4a:
        # FAAC 1.28 doesn't work with standard inputs. This code is useless.
        printstr("ripping " + file_prefix + ".m4a ...\n")
        m4aPipe = Popen(["faac",
                        "-P",
                        "-R", str("44100"),
                        "-w",
                        "-s",
                        "-q", str("400"),
                        "--genre", str(defaultgenre),
                        "--title", str(track.name()),
                        "--artist", u' • '.join([str(x.name()) for x in track.artists()]),
                        "--album", str(track.album()),
                        "--year", str(track.album().year()),
                        "--track", str("%02d" % (track.index(),)),
#                        "--cover-art", str(directory + "/folder.jpg"),
                        "--comment", "Spotify PCM + 'faac -q 400'",
                        "-o", file_prefix + ".m4a",
                        "-"],
            stdin=PIPE)
        
        pipe.append(m4aPipe.stdin)

    if mp3:
        printstr("ripping " + file_prefix + ".mp3 ...\n")
        mp3Pipe = Popen(["lame",
                        "--silent",
                        "-V2",       # VBR slightly less than highest quality
                        "-m", "s",   # plain stereo (no joint stereo)
                        "-h",        # high quality, same as -q 2
                        "-r",        # input is raw PCM
                        "--id3v2-utf16",
                        "--id3v2-only",
                        "--tg", str(defaultgenre),
                        "--tt", str(track.name()),
                        "--ta", u' • '.join([str(x.name()) for x in track.artists()]),
                        "--tl", str(track.album()),
                        "--ty", str(track.album().year()),
                        "--tn", str("%02d" % (track.index(),)),
                        "--tc", "Spotify PCM + 'lame -V2 -m s -h'",
                        "-", file_prefix + ".mp3"],
            stdin=PIPE)
            
        pipe.append(mp3Pipe.stdin)
    
    if wav:
        wavPipe=Popen(["ffmpeg",
                        "-loglevel", "quiet",
                        "-f", "s16le",
                        "-ar", "44100",
                        "-ac", "2",
                        "-i", "-",
                        file_prefix + ".wav"],
        stdin=PIPE)
        
        pipe.append(wavPipe.stdin)
    
    ripping = True


def rip_terminate(session, track):
    global ripping, pipe, pcmfile, rawpcm

    if pipe is not None:
        for p in pipe:
            p.close()
        print(' done!')

    ripping = False


# This callback is called for each frame of each track
def rip(session, frames, frame_size, num_frames, sample_type, sample_rate, channels):
    global size, feedbackchar, feedbackcharDelay

    sys.stdout.write('\r' + feedbackchar)
    sys.stdout.flush()

    if feedbackcharDelay > 5:
        feedbackcharDelay = 0
        if feedbackchar == '-':
            feedbackchar='\\'
        elif feedbackchar == '\\':
            feedbackchar='|'
        elif feedbackchar == '|':
            feedbackchar='/'
        elif feedbackchar == '/':
            feedbackchar='-'

    feedbackcharDelay += 1
        
#    printstr('.')
#    printstr("frame_size={}, num_frames={}, sample_type={}, sample_rate={}, channels={}\n".format(
#    	frame_size, num_frames, sample_type, sample_rate, channels))

#    pprint.pprint(pipe)

    for p in pipe:
        p.write(frames)

#     if ripping:
#         pipe.write(frames);
# #        printstr("     " + size + " bytes\r")
#         if wav:
#           wpipe.write(frames)

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
    
#     spotify_links="Spotify track: {0}\nSpotify album: {1}".format(
#         track.link().url,
#         oalbum.link().url
#     )

    # write id3 data
#     call(["eyeD3",
#           "--add-image", directory + "/folder.jpg:FRONT_COVER",
#           "-t", track_name,
#           "-a", track_artist,
#           "-b", album_artist,
#  #         "-c", spotify_link,
#           "-A", album_name,
#           "-n", num_track,
#           "-Y", year,
#           "--to-v2.3",
#           "-Q",
#           mp3file
#     ])


#    id3.ID3_DEFAULT_VERSION = (2, 3, 0)

    audiofile = eyed3.load(mp3file)
    audiofile.initTag()
    
    audiofile.tag.album_artist    = album_artist
    audiofile.tag.album           = album_name
    audiofile.tag.release_date    = year
    audiofile.tag.recording_date  = year
    audiofile.tag.original_release_date    = year
    audiofile.tag.artist          = track_artist
    audiofile.tag.track_num       = (num_track, None)
    audiofile.tag.title           = track_name
    audiofile.tag.genre           = defaultgenre
#    audiofile.tag.comments.set(     spotify_links)

    # append image to tags
#     audiofile.tag.images.set(3,image.data(),
#         u'image/jpeg',
#         u'Front Cover'
#     )

	# Save ID3 using version 2.3 for maximum compatibility. UTF-16 is required for 2.3
    audiofile.tag.save(version=(2, 3, 0), encoding='utf16')
    




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
                # rip_id3(session, track)

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
