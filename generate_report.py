from ws4py.client.threadedclient import WebSocketClient
import argparse
import base64
import time
from threading import Thread
from os import walk
import json
import copy

def read_in_chunks(file_object, chunk_size=1024):
    while True:
	data = file_object.read(chunk_size)
	if not data:
	    break
	yield data

def get_answerkeymap(filename):
    akmap = {}
    import csv
    with open(filename, 'rb') as csvfile:
        csv_reader = csv.reader(csvfile, delimiter='\t')
        for r in csv_reader:
            akmap[r[1]] = r
    return akmap

class DummyClient(WebSocketClient):
    result = {}

    def opened(self):
	print "Websocket Opened"
	msg_start = "{\"action\": \"start\", \"content-type\": \"audio/l16;rate=16000\", \"continuous\":true, \"interim_results\":true}"
	print ">> ", msg_start
	self.send( msg_start )
		
    def closed(self, code, reason=None):
	print "CLOSED", code, reason

    def send_audio(self, fn):
        for i in range(1,2):
	    print ">> sending audio in chunks, number ", i
            f = open(fn, 'rb')
	    for piece in read_in_chunks(f):
		self.send(piece, True)
	    f.close()
	msg_stop = "{\"action\":\"stop\"}"
	print ">> ", msg_stop
	self.send(msg_stop)

    def received_message(self, m):
	print "<< ", m
        reply = json.loads(str(m))
        try:
            if "error" in reply.keys():
                print "ERROR reply, returning from received_message"
                return
            if "results" in reply.keys():
                if reply["results"][0]["final"] is True:
                    self.result["stt_conf"]=reply["results"][0]["alternatives"][0]["confidence"]
                    self.result["stt_trans"]=reply["results"][0]["alternatives"][0]["transcript"]
            if "responses" in reply.keys():
                self.result["actual_res"] = ""
                for i in range(len(reply['responses'])):
                    item = reply['responses'][i]
                    if item['item_type'] == 'dialog':
                        self.result['actual_res'] += " "+(item['text'])
                    if item['item_type'] == 'intent':
                        self.result["NLC_class1"]=item['text']
                        self.result["NLC_class1_conf"]=item['confidence']
                        self.result["NLC_class2"]=reply['responses'][i+1]['text']
                        self.result["NLC_class2_conf"]=reply['responses'][i+1]['confidence']
                        break
                results.append(copy.deepcopy(self.result))
                self.result = {}
                self.close(reason="received expected responses")
                print "close websocket after receiving response"
        except Exception as e:
            print e
            self.result = {}
            self.close(reason="EXCEPTION")
            print "close websocket after exception"

if __name__ == '__main__':
    import sys
    from optparse import OptionParser
        
    parser = OptionParser()
    parser.add_option("-d", "--dir", dest="directory",
                          help="directory where all the audio files are stored")
    parser.add_option("-s", "--server", dest="server",
                          help="server url to connect to ex: sjr-robot-app.mybluemix.net")
    parser.add_option("-a", "--answerkey", dest="answerkey",
                          help="answerkey from SME for evaluation in csv file, tab separated")
    (options, args) = parser.parse_args()

    if options.directory is None:
        print "please use -d to set the directory where the audio files are stored"
        sys.exit()
    if options.server is None:
        print "please use -s to set server url "
        sys.exit()
    if options.answerkey is None:
        print "please use -a to set answerkey file"
        sys.exit()
    if ".csv" not in options.answerkey:
        print "please make sure the answerkey file is in csv format"
        sys.exit()

    ws_url = "wss://" + options.server + "/wim/hc/v1/speech-to-text"
    print ws_url
    
    username = "apiuser"
    password = "r0b0tsrul3"
    base64string = base64.encodestring('%s:%s' % (username, password)).replace('\n', '')
        
    results = []
    global results

    answerkeymap = get_answerkeymap(options.answerkey)

    for (dirpath, dirnames, filenames) in walk(options.directory):
        for f in filenames:
            if 'wav' not in f:
                continue
            print "processing file"+f
            if f not in answerkeymap.keys():
                print "no answer key found for "+f
                continue
            try:
                ws = DummyClient(ws_url, headers=[('Authorization','Basic %s' % base64string)])
		ws.connect()
                ws.result['filename'] = f
                ws.send_audio('{}/{}'.format(str(dirpath),f))
                ws.run_forever()
            except KeyboardInterrupt:
                sys.exit(0)
            except Exception as e:
                print e
            except ssl.SSLError as e:
                print e
    import codecs
    print "Generating report"
    fields = ["stt_trans","stt_conf","actual_res","NLC_class1","NLC_class1_conf","NLC_class2","NLC_class2_conf"]
    with codecs.open('report.csv','w',encoding='utf-8') as f:
        # header 
        for col in answerkeymap["Audio File"]:
            f.write("{}\t".format(col))
        for col in fields:
            f.write("{}\t".format(col))
        f.write("\n")
        # row
        for r in results:
            print r
            row = ''
            try:
                for col in answerkeymap[r["filename"]]:
                    row += "{}\t".format(col)
                for col in fields:
                    row += "{}\t".format(r[col])
                row += "\n"
                f.write(row.encode('utf-8'))
            except KeyError as e:
                print "Can't find the answerkey for the following file"
                print e
                continue
            except Exception as e:
                print e
                continue
    print "DONE"
