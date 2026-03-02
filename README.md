<h1>Authenticated Web Health Checker</h1>

## About the Project
This is a script that allows the user to crawl a website and check the frontend of all its pages. The idea is to recursively check for any HTML errors for a Wordpress site after any updates and/or code changes. At the moment, we are only checking for HTML errors but the intention is to expand the functionality to check for any errors that still result in a 200 and so forth.

Authentication is optional and only necessary in the event that the website being tested has content pages gated behind a login. In that case, please use a json file with the following keys:

"login_url", (the action URL of the applicable login form)
"username",
"password"