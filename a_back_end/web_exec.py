#!/usr/bin/env python3

# Online Python Tutor
# Copyright (C) 2010-2011 Philip J. Guo (philip@pgbovine.net)
# https://github.com/pgbovine/OnlinePythonTutor/
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


# Executes the Online Python Tutor back-end as a CGI script, which
# accepts one POST parameter, 'user_script', containing the string
# contents of the Python script that the user wants to execute.
#
# Returns a complete JSON execution trace to the front-end.
#
# This version uses Python 2.5 on the MIT CSAIL servers.
# (note that Python 2.4 doesn't work on CSAIL, but Python 2.5 does)
#
# If you want to run this script, then you'll need to change the
# shebang line at the top of this file to point to your system's Python.
#
# Also, check CGI execute permission in your script directory.
# You might need to create an .htaccess file like the following:
#
#   Options +ExecCGI
#   AddHandler cgi-script .py

import json

# set to true if you want to log queries in DB_FILE 
LOG_QUERIES = False  # don't do logging for now

if LOG_QUERIES:
    import os
    import time
    import db_common


def web_finalizer(output_lst):
    # use compactly=False to produce human-readable JSON,
    # except at the expense of being a LARGER download
    output_json = json.dumps(output_lst)

    # query logging is optional
    if LOG_QUERIES:
        # just to be paranoid, don't croak the whole program just
        # because there's some error in logging it to the database
        try:
            # log queries into sqlite database:
            had_error = False
            # (note that the CSAIL 'www' user needs to have write permissions in
            #  this directory for logging to work properly)
            if len(output_lst):
                evt = output_lst[-1]['event']
                if evt == 'exception' or evt == 'uncaught_exception':
                    had_error = True

            (con, cur) = db_common.db_connect()
            cur.execute("INSERT INTO query_log VALUES (NULL, ?, ?, ?, ?, ?)",
                        (int(time.time()),
                         os.environ.get("REMOTE_ADDR", "N/A"),
                         os.environ.get("HTTP_USER_AGENT", "N/A"),
                         user_script,
                         had_error))
            con.commit()
            cur.close()
        except:
            # haha this is bad form, but silently fail on error :)
            pass

    # Crucial first line to make sure that Apache serves this data
    # correctly - DON'T FORGET THE EXTRA NEWLINES!!!:
    print("Content-type: text/plain; charset=iso-8859-1\n\n")
    print(output_json)
    return output_json
