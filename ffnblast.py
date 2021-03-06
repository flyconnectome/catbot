"""
    Fire and forget nblasting
    ffnblast.py is part of Catbot (https://github.com/flyconnectome/catbot)
    Copyright (C) 2017 Philipp Schlegel

    Call from shell or using subprocess.Popen('python ffnblast <skid> <channel>')
    Will post results in slack channel and upload a webGL file containg the first 3 hits.

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import rpy2.robjects as robjects
from rpy2.robjects.packages import importr
import json, logging
from tabulate import tabulate
from slackclient import SlackClient

if __name__ == '__main__':
    import sys
    import botconfig

    #Skid of the neuron to NBLAST and Slack channel to post the response to have to be passed as arguments
    skid = sys.argv[1]
    channel = sys.argv[2]
    mirror = bool(int( sys.argv[3]))
    hits = int(sys.argv[4])
    db = sys.argv[5]
    cores = int(sys.argv[6])
    prefer_muscore = bool( int( sys.argv[7]))
    use_alpha = bool(int( sys.argv[8]))
    reverse = False

    #Create logger
    logger = logging.getLogger('fire-n-forget NBLAST')
    logger.setLevel(logging.INFO)
    #Create console handler - define different log level is desired
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    #Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    #Add the handlers to the logger
    logger.addHandler(ch)

    #Initialize slack client from botconfig.py
    slack_client = SlackClient( botconfig.SLACK_KEY)
    logger.debug('Connection to Slack:', slack_client.rtm_connect())

    logger.info('Blasting neuron #%s (mirror=%s; reverse=%s; hits=%i; db=%s; use_alpha=%s; prefer_reverse_score=%s) - please wait...' % ( skid, mirror, reverse, hits, db, use_alpha, prefer_muscore ) )
    ts = slack_client.api_call("chat.postMessage", channel=channel, text='Blasting neuron #%s `( mirror=%s; reverse=%s; hits=%i; db=%s; use_alpha=%s; prefer_reverse_score=%s )` - please wait...' % ( skid, mirror, reverse, hits, db, use_alpha, prefer_muscore ) , as_user=True)['ts']

    #Import R libraries
    elmr = importr('elmr')
    fc = importr('flycircuit')
    domc = importr('doMC')
    rjson = importr('rjson')
    cores = robjects.r('registerDoMC(%i)' % cores)
    vfbr = importr('vfbr')

    #Make sure variables for databases are set correctly
    login = robjects.r('options(catmaid.server="%s", catmaid.authname="%s",catmaid.authpassword="%s", catmaid.token="%s")' % ( botconfig.SERVER_URL, botconfig.HTTP_USER, botconfig.HTTP_PW, botconfig.AUTHTOKEN ) )
    fcdps = robjects.r('fcdps<-read.neuronlistfh("%s", localdir=getOption("flycircuit.datadir"))' % botconfig.FLYCIRCUIT_DB )
    gmrdps = robjects.r('gmrdps<-read.neuronlistfh("%s", localdir=getOption("flycircuit.datadir"))' % botconfig.JANELIA_GMR_DB )
    #robjects.r('remotesync(dps,download.missing = TRUE)')

    #The dps objects are essentially on-demand, meaning that once in python they remain essentially empty
    #To access the neurons' dotproducts, do e.g. this: dp = robjects.r(fcdps[[1]])
    #This will then have three entries: ['points', 'alpha', 'vect']

    #Make R functions callable in Python
    nblast_fafb = robjects.r('nblast_fafb')
    summary = robjects.r('summary')
    toJSON = robjects.r('toJSON')
    row_names = robjects.r('row.names')
    fc_neuron = robjects.r('fc_neuron')
    vfb_tovfbids = robjects.r('vfb_tovfbids')
    gmr_vfbid = robjects.r('gmr_vfbid')
    rainbow = robjects.r('rainbow')

    logger.debug('Blasting - please wait...')

    if db == 'fc':
        res = nblast_fafb(int(skid), mirror=mirror, reverse=reverse,
                          db=fcdps, UseAlpha=use_alpha)
        su = summary(res, db=fcdps)
    elif db == 'gmr':
        res = nblast_fafb(int(skid), mirror=mirror, reverse=reverse,
                          db=gmrdps, UseAlpha=use_alpha)
        su = summary(res, db = gmrdps)

    #Read results into python data objects
    #summary = dict( zip( su.names, map( list, list( su ) ) ) )
    s = []
    for i, c in enumerate(list(row_names(su))):
        s.append( {
                    'name': c,
                    'score': su[0][i],
                    'muscore': su[1][i],
                    'ntype': su[2][i],
                    'glom': su[3][i],
                    'Driver': su[4][i],
                    'Gender': su[5][i],
                    'n': su[6][i]
                } )

    results = json.loads(toJSON(res)[0])

    #Generate a 3d html from the results
    plot3d = robjects.r('plot3d')
    writeWebGL = robjects.r('writeWebGL')

    #Summary comes ordered by reverse score (muscore). However, the hits are based solely on forward score
    #If we prefer muscore, use hit numbers ('n') of the first few entries and then assign new the hit numbers
    if not prefer_muscore:
        h = robjects.IntVector(range(hits + 1))
        hit_names = []
        for i in range(hits):
            hit_names.append([e['name'] for e in s if e['n'] == i+1][0])
    else:
        h = robjects.IntVector([e['n'] for e in s[:hits]])
        hit_names = [e['name'] for e in s[:hits]]
        #Reassign the 'n' (hit) value
        for i, n in enumerate(s):
            s[i]['n'] = i+1

    if db == 'fc':
        plot3d(res, hits=h, db=fcdps, soma=True)
    elif db == 'gmr':
        plot3d(res, hits=h, db=gmrdps, soma=True)

    writeWebGL('webGL', width=1000)
    robjects.r('rgl.close()')

    logger.debug('Finished nblasting neuron', skid)

    slack_client.api_call("chat.delete",
                          channel=channel,
                          ts=ts)

    if db == 'fc':
        table = [['*Gene Name*', '*Score*', '*MuScore*', '*Driver*',
                  '*Gender*', '*VFB*', '*Hit No.*']]
        fc_urls = {}
        vfb_urls = {}
        for e in s:
            #e['name'] is gene name -> use fc_neuron to get neuron name
            neuron_name = fc_neuron(e['name'])[0]
            try:
                vfb_id = vfb_tovfbids(neuron_name)[0]
            except:
                #This may fail if VFB server is - for some reason - not available
                vfb_id = None
            if type(vfb_id) == type(str()):
                vfb_urls[vfb_id] = 'http://www.virtualflybrain.org/site/stacks/index.htm?id=%s' % vfb_id
            else:
                vfb_id = 'N/A'
            fc_urls[neuron_name] = 'http://flycircuit.tw/flycircuitSourceData/NeuronData/%s/%s_lsm.png' % (neuron_name, neuron_name)
            table.append([e['name'],
                          round(e['score'], 3),
                          round(e['muscore'], 3),
                          e['Driver'],
                          e['Gender'],
                          vfb_id,
                          e['n']])
    else:
        table = [['*Name*', '*Score*', '*MuScore*', '*VFB*', '*Hit No.*']]
        vfb_urls = {}
        for e in s:
            try:
                vfb_id = gmr_vfbid(e['name'])[0]
            except:
                #This may fail if VFB server is - for some reason - not available
                vfb_id = None
            if type(vfb_id) == type(str()):
                vfb_urls[vfb_id] = 'http://www.virtualflybrain.org/site/stacks/index.htm?id=%s' % vfb_id
            else:
                vfb_id = 'N/A'
            table.append([e['name'],
                          round(e['score'], 3),
                          round(e['muscore'], 3),
                          vfb_id,
                          e['n']])

    tab = tabulate(table)
    for vfb_id in vfb_urls:
        tab = tab.replace(vfb_id , '<%s|%s>' % (vfb_urls[vfb_id], vfb_id))

    slack_client.api_call("chat.postMessage",
                          channel=channel,
                          text= '```' + tab + '```',
                          as_user=True)

    with open('webGL/index.html', 'r') as f:
        slack_client.api_call("files.upload", channels=channel,
                              file=f,
                              title='3D nblast results for neuron #%s' % skid,
                              initial_comment='Open file in browser'
                              )
    #Color palette is based on R's rainbow() -> we have to strip the last two values (those are alpha)
    colors = [e[:-2] for e in list(rainbow(hits))]
    legend = '\n'.join(list(map(lambda c,n : c + ' - ' + n, colors, hit_names)))
    slack_client.api_call("chat.postMessage", channel=channel,
                          text=legend, as_user=True)