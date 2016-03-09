from ws4py.client.threadedclient import WebSocketClient
from difflib import SequenceMatcher
import argparse
import base64
import time
from threading import Thread
from os import walk
import json
import copy

def is_correct(ref, hyp):
    if SequenceMatcher(None, ref, hyp).ratio() < 0.9:
        return False
    else:
        return True

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
            akmap[r[1]] = {
                "time_stamp":r[0],
                "audio_file":r[1],
                "utterance":r[2],
                "type":r[3],
                "right_answer":r[4]
            }
    return akmap

def wer(ref, hyp):
    r = ref.lower().split()
    if len(r) is 0:
        raise ValueError("first argument ref sentence can't be empty")
    h = hyp.lower().split()
    # initialisation
    import numpy
    d = numpy.zeros((len(r)+1)*(len(h)+1), dtype=numpy.uint8)
    d = d.reshape((len(r)+1, len(h)+1))
    for i in range(len(r)+1):
        for j in range(len(h)+1):
            if i == 0:
                d[0][j] = j
            elif j == 0:
                d[i][0] = i
    # computation
    for i in range(1, len(r)+1):
        for j in range(1, len(h)+1):
            if r[i-1] == h[j-1]:
                d[i][j] = d[i-1][j-1]
            else:
                substitution = d[i-1][j-1] + 1
                insertion    = d[i][j-1] + 1
                deletion     = d[i-1][j] + 1
                d[i][j] = min(substitution, insertion, deletion)
    
    return d[len(r)][len(h)]/(len(r)*1.0)

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
                        self.result["NLC_class1_conf"]=float("{:6.3f}".format(item['confidence']))
                        self.result["NLC_class2"]=reply['responses'][i+1]['text']
                        self.result["NLC_class2_conf"]=float("{:6.3f}".format(reply['responses'][i+1]['confidence']))
                        break
                ak = answerkeymap[self.result["filename"]]
                self.result['wer'] = float("{:6.3f}".format(wer(ak['utterance'],self.result["stt_trans"])))
                self.result['response_is_correct'] = is_correct(ak["right_answer"],self.result["actual_res"])
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
    global results
    results = []

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
    fields = ["time_stamp","audio_file","type","utterance",
              "stt_trans","stt_conf",'wer',
              "right_answer","actual_res",'response_is_correct',
              "NLC_class1","NLC_class1_conf","NLC_class2","NLC_class2_conf"]
    
    with codecs.open('report.csv','w',encoding='utf-8') as f:
        # header 
        for col in fields[:-1]:
            f.write("{}\t".format(col))
        f.write("{}\n".format(fields[-1]))
        # row
        for r in results:
            print r
            row = ''
            try:
                ak = answerkeymap[r["filename"]]
                ak.update(r)
                for k in fields[:-1]:
                    row += "{}\t".format(ak[k])
                row += "{}\n".format(ak[fields[-1]])
                f.write(row.encode('utf-8'))
            except KeyError as e:
                print "KeyError exception or no answerKey is found for certain file"
                print e
                continue
            except Exception as e:
                print e
                continue
    print "DONE"
