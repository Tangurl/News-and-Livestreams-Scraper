@echo off
setlocal
title Facebook Login
pushd "%~dp0CredentialsUtility"
python login_facebook.py
popd
pause
