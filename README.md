# catbot
Python (>=3.6) Slack bot to interface [CATMAID](https://github.com/catmaid/CATMAID)
with [NBLAST](https://github.com/jefferislab/nat.nblast). Based on
[Slack's Python API](https://github.com/slackapi/python-slackclient) (see [here](https://slackapi.github.io/python-slackclient/) for documentation).

# Quickstart
1. Clone this repository
2. Complete the botconfig.py (see below)
3. Install dependencies for R and Python
4. Run catbot.py: `python3 catbot.py`
5. In Slack use `@catbot help` to get a list of possible commands

# Dependencies
## Python
[slackclient](https://github.com/slackapi/python-slackclient),
[matplotlib](http://matplotlib.org/),
[pymaid](https://github.com/schlegelp/pymaid),
[tabulate](https://github.com/gregbanks/python-tabulate),
[rpy2](https://rpy2.readthedocs.io/en/version_2.8.x/),
[certifi](https://pypi.org/project/certifi/)

## R
[elmr](https://github.com/jefferis/elmr) and dependencies,
[flycircuit](https://github.com/jefferis/flycircuit),
[vfbr](https://github.com/jefferis/vfbr),
[doMC](https://cran.r-project.org/web/packages/doMC/index.html)
[rjson](https://cran.r-project.org/web/packages/rjson/index.html)

# Configuration
botconfig.py needs to hold credentials for Slack and your CATMAID server:

`BOT_NAME` is the name of your bot (e.g. "catbot").

`BOT_USER_OAUTH_ACCESS_TOKEN` is your bot's OAuth token.

See [here](https://api.slack.com/bot-users) on how to setup your bot and retrieve the AUTHTOKEN.

`MAX_PARALLEL_REQUESTS` sets the max number of parallel requests the bot will process before complaining.

`CATMAID_SERVER_URL`, `CATMAID_AUTHTOKEN`, `CATMAID_HTTP_USER`, `CATMAID_HTTP_PW` and `CATMAID_PROJECT_ID` are your CATMAID credentials.

See [here](https://catmaid.readthedocs.io/en/stable/api.html#api-token) how to retrieve your API token.

`FLYCIRCUIT_DB` and `JANELIA_GMR_DB` are the URLs to the respective databases for nblast.

`FAFB_DUMP` is the path to the file that contains the overnight neuron dump.

# Using catbot to NBLAST
Use `@catbot nblast #skid` to have catbot perform a nblast search. This relies on R being installed and setup to use [elmr](https://github.com/jefferis/elmr) and its dependencies. Please make sure that you can run e.g. the example in `?elmr::nblast_fafb`

Catbot will return a list of top hits and their nblast scores plus a .html file containing a WebGL rendering of the first few hits (see screenshot).

![nblast_example](https://cloud.githubusercontent.com/assets/7161148/23308336/ce5682be-faa2-11e6-9400-6bdb369f1b15.png)

<img src="https://cloud.githubusercontent.com/assets/7161148/23557599/76695c44-0028-11e7-94dd-a9bd6edbb746.png" alt="nblast_webGL_result" width="500">

## License:
This code is under GNU GPL V3
