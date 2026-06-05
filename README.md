# site-health-checker

This is a CLI tool for checking website health built with Python.

## installation

This is installed by downloading/cloning the repo and running ``pipx install`` within its directory on your machine.

## usage

Run ``shcheck {website url}``


| Options | Function |
| ------- | -------- |
| -d, --delay | sets delay in seconds, defaults to 0.1 |
| -t, --timeout | sets timeout in seconds, defaults to 10 |
| -o, --output | optional filepath destination for output file |
| -e, --excluded | comma separated values of paths to exclude |
| -lf, --login-file | location for login credential JSON {login_url, username, password} |
| -c, --cookie | pass authentication cookie payload directly into session header |
| -sm, --sitemap | exact sitemap path if you know it, may allow for faster crawling |
| -sp, --spider | boolean for forcing spider crawl |
| -w, --workers | Number of simultaneous processes |