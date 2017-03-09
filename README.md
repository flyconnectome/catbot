# catbot
Python 3 Slack bot to interface with [CATMAID](https://github.com/catmaid/CATMAID) server, [NBLAST](https://github.com/jefferislab/nat.nblast) and [Zotero](https://www.zotero.org/). Based on [Slack's Python API](https://github.com/slackapi/python-slackclient) (see [here](https://slackapi.github.io/python-slackclient/) for documentation).

# Quickstart 
1. Download catbot.py, botconfig.py and ffnblast.py
2. Setup and configure botconfig.py (see below)
3. Install dependencies
4. Run catbot.py
5. In Slack use `@catbot help` to get a list of possible commands

# Dependencies 
[slack_client](https://github.com/slackapi/python-slackclient),
[matplotlib](http://matplotlib.org/),
[pymaid](https://github.com/schlegelp/pymaid),
[tabulate](https://github.com/gregbanks/python-tabulate),
[rpy2](https://rpy2.readthedocs.io/en/version_2.8.x/),
[pyzotero](https://github.com/urschrei/pyzotero)

# Configuration
botconfig.py needs to hold credentials for CATMAID server, Slack and Zotero (optional)
```python
#General parameters
BOT_NAME = 'catbot'
BOT_ID = ''
AT_BOT = '<@' + BOT_ID + '>'
READ_WEBSOCKET_DELAY = 1 # 1 second delay between reading from firehose
MAX_PARALLEL_REQUESTS = 10 # not more than 10 threads at any given time

#Catmaid credentials
SERVER_URL = ''
AUTHTOKEN = ''
HTTP_USER = ''
HTTP_PW = ''

#Slack credentials
SLACK_KEY = ''

#Zotero credentials
ZOT_KEY = ''
ZOT_GRP_ID = ''
```
See [here](https://api.slack.com/bot-users) on how to setup bot_id and Slack key 

See [here](https://github.com/urschrei/pyzotero) on Zotero keys and grp ids.

# Using catbot to NBLAST
Use `@catbot nblast #skid` to have catbot perform a nblast search. This relies on R being installed and configured to use [elmr](https://github.com/jefferis/elmr) and its dependencies.

Catbot will return a list of top hits and their nblast scores, and a .html file containing a WebGL rendering of the first few hits (see screenshot).

![nblast_example](https://cloud.githubusercontent.com/assets/7161148/23308336/ce5682be-faa2-11e6-9400-6bdb369f1b15.png)

<img src="https://cloud.githubusercontent.com/assets/7161148/23557599/76695c44-0028-11e7-94dd-a9bd6edbb746.png" alt="nblast_webGL_result" width="500">

Optional arguments:

`nomirror` to set mirror=F (default = T)

`hits=N` to set number of hits to include in the 3D WebGL file (default = 3)

## License:
This code is under GNU GPL V3
