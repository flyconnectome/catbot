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

import os.path

import pymaid
pymaid.set_pbars(hide=True)
pymaid.set_loggers('ERROR')

import pandas as pd

if __name__ == '__main__':
    import sys
    import botconfig

    #Skid of the neuron to NBLAST and Slack channel to post the response to have to be passed as arguments
    skid = sys.argv[1]
    channel = sys.argv[2]
    mirror = bool(int(sys.argv[3]))
    hits = int(sys.argv[4])
    cores = int(sys.argv[5])
    prefer_muscore = bool(int(sys.argv[6]))
    use_alpha = bool(int(sys.argv[7]))
    reverse = False

    #Create logger
    logger = logging.getLogger('fire-n-forget FAFB NBLAST')
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
    slack_client = SlackClient(botconfig.SLACK_KEY)
    logger.debug('Connection to Slack:', slack_client.rtm_connect())

    logger.info('Blasting neuron #%s (mirror=%s; reverse=%s; hits=%i;'
                ' use_alpha=%s; prefer_reverse_score=%s) - please wait...'
                '' % (skid, mirror, reverse, hits, use_alpha,
                      prefer_muscore))
    ts = slack_client.api_call("chat.postMessage", channel=channel,
                               text='Blasting neuron #%s `(mirror=%s; '
                                    'reverse=%s; hits=%i; use_alpha=%s; '
                                    'prefer_reverse_score=%s)` '
                                    '- please wait...' % (skid, mirror,
                                                          reverse, hits,
                                                          use_alpha,
                                                          prefer_muscore),
                               as_user=True)['ts']

    #Import R libraries
    nat = importr('nat')
    elmr = importr('elmr')
    fc = importr('flycircuit')
    domc = importr('doMC')
    rjson = importr('rjson')
    cores = robjects.r('registerDoMC(%i)' % cores)
    vfbr = importr('vfbr')
    catmaid = importr('catmaid')
    nat_flybrains = importr('nat.flybrains')
    nat_templatebrains = importr('nat.templatebrains')
    r_nblast = importr('nat.nblast')
    rmarkdown = importr('rmarkdown')

    # Make connection to Catmaid
    login = robjects.r('options(catmaid.server="{}", catmaid.authname="{}", '
                       'catmaid.authpassword="{}", catmaid.token="{}")'.format(botconfig.SERVER_URL,
                                                                               botconfig.HTTP_USER,
                                                                               botconfig.HTTP_PW,
                                                                               botconfig.AUTHTOKEN))
    rm = pymaid.CatmaidInstance(botconfig.SERVER_URL,
                                botconfig.HTTP_USER,
                                botconfig.HTTP_PW,
                                botconfig.AUTHTOKEN)

    # If there already is a DPS file from the nightly dump use this
    p = os.path.join(botconfig.FAFB_DUMP, 'fulln.simp10.dps.rda')
    if os.path.isfile(p):
        _ = robjects.r('load("{}")'.format(p))
        fulln_simp10_dps = robjects.r('fulln.simp10.dps')
    else:
        # Generate dps (note the conversion to um!)
        p = os.path.join(botconfig.FAFB_DUMP, 'fulln.simp10.rda')
        _ = robjects.r('load("{}")'.format(p))
        fulln_simp10_dps = robjects.r("dotprops(fulln.simp10/1e3, k=5, "
                                      "resample=1, .parallel=T, "
                                      "OmitFailures=T)")

    #Make R functions callable in Python
    rainbow = robjects.r('rainbow')

    # Load the neuron of interest
    _ = robjects.r('n = read.neurons.catmaid({})'.format(skid))

    # Mirror neuron if necessary
    if mirror:
        # Convert to JFRC2
        _ = robjects.r('n.jfrc2 = xform_brain(n, sample=FAFB14, reference=JFRC2)')
        # Mirror
        _ = robjects.r('n.mirrored = mirror_brain(n.jfrc2, brain=JFRC2)')
        # Convert back to FAFB
        _ = robjects.r('n = xform_brain(n.mirrored, sample=JFRC2, reference=FAFB14)')

    # Simplify neuron to same degree as FAFB dump
    _ = robjects.r('n.simp = simplify_neuron(n[[1]], n=10, OmitFailures=T, .parallel=T)')

    # Convert to dotprops (also note the conversion to um!)
    _ = robjects.r('n.simp.dps = dotprops(n.simp/1e3, k=5, resample=1, .parallel=T, OmitFailures=T)')

    # Get the neuron into Python
    xdp = robjects.r('n.simp.dps')

    # Now NBLAST

    # Number of reverse scores to calculate (max 100)
    nrev = min(100, len(fulln_simp10_dps))

    if reverse:
        sc = r_nblast.nblast(fulln_simp10_dps,
                             nat.neuronlist(xdp),
                             **{'normalised': True,
                                '.parallel': True,
                                'UseAlpha': use_alpha})

        # Have to convert to dataframe to sort them -> using
        # 'robjects.r("sort")' looses the names for some reason
        sc_df = pd.DataFrame([[sc.names[0][i], sc[i]] for i in range(len(sc))],
                             columns=['name', 'score'])
        sc_df.sort_values('score', ascending=False, inplace=True)

        # Use ".rx()" like "[]" and "rx2()" like "[[]]" to extract subsets of R
        # objects
        scr = r_nblast.nblast(nat.neuronlist(xdp),
                              fulln_simp10_dps.rx(robjects.StrVector(sc_df.name.tolist()[:nrev])),
                              **{'normalised': True,
                                 '.parallel': True,
                                 'UseAlpha': use_alpha})
    else:
        sc = r_nblast.nblast(nat.neuronlist(xdp), fulln_simp10_dps, **
                             {'normalised': True,
                              '.parallel': True,
                              'UseAlpha': use_alpha})

        # Have to convert to dataframe to sort them -> using
        # 'robjects.r("sort")' looses the names for some reason
        sc_df = pd.DataFrame([[sc.names[0][i], sc[i]] for i in range(len(sc))],
                             columns=['name', 'score'])
        sc_df.sort_values('score', ascending=False, inplace=True)

        # Use ".rx()" like "[]" and "rx2()" like "[[]]" to extract subsets of R
        # objects
        scr = r_nblast.nblast(fulln_simp10_dps.rx(robjects.StrVector(sc_df.name.tolist()[:nrev])),
                              nat.neuronlist(xdp),
                              **{'normalised': True,
                                 '.parallel': True,
                                 'UseAlpha': use_alpha})

        sc_df.set_index('name', inplace=True, drop=True)

        res = pd.DataFrame([[scr.names[i],
                             sc_df.loc[scr.names[i]].score,
                             scr[i],
                             (sc_df.loc[scr.names[i]].score + scr[i]) / 2]
                           for i in range(len(scr))],
                          columns=['skeleton_id', 'forward_score',
                                   'reverse_score', 'mu_score']
                          )

    if prefer_muscore:
        res = res.sort_values('mu_score', ascending=False)
    else:
        res = res.sort_values('forward_score', ascending=False)


    names = pymaid.get_names(res.skeleton_id.values)
    res['neuron_name'] = res.skeleton_id.map(names)

    res = res[['neuron_name', 'skeleton_id', 'forward_score',
               'reverse_score', 'mu_score']]

    # Retrieve the "full neurons" from CATMAID
    hit_skids = res.skeleton_id.values[:hits+1]
    hit_names = res.neuron_name.values[:hits+1]
    robjects.r('to_plot = read.neurons.catmaid(c({}))'.format(','.join(hit_skids)))

    # First plot the original neuron in black
    robjects.r('plot3d(n, color="black", soma=T)')

    # Now plot the first N hits
    robjects.r('plot3d(to_plot, soma=T)')

    # Save as RGL plot as WebGL and close
    robjects.r('writeWebGL("webGL", width=1000)')
    robjects.r('rgl.close()')

    logger.debug('Finished nblasting neuron', skid)

    slack_client.api_call("chat.delete",
                          channel=channel,
                          ts=ts)

    slack_client.api_call("chat.postMessage", channel=channel,
                          text= '```{}```'.format(res.head(max(10, hits)).to_string()),
                          as_user=True)

    with open('webGL/index.html', 'r') as f:
        slack_client.api_call("files.upload", channels=channel, file=f,
                             title='3D nblast results for neuron #%s' % skid,
                             initial_comment='Open file in browser'
                             )
    #Color palette is based on R's rainbow() -> we have to strip the last two values (those are alpha)
    colors = [e[:-2] for e in list(rainbow(hits))]
    legend = '\n'.join(list(map(lambda c,n : c + ' - ' + n, colors, hit_names)))
    slack_client.api_call("chat.postMessage", channel=channel,
                          text=legend, as_user=True)