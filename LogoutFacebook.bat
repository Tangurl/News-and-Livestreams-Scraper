@echo off
setlocal
title Facebook Logout
pushd "%~dp0CredentialsUtility"
python logout_facebook.py
popd
pause
