# Thin wrapper: jarvis inject (Mark XXVII) - forwards all arguments.
# Examples:
#   .\scripts\inject.ps1 scan
#   .\scripts\inject.ps1 install -Target 192.168.1.50 -OS linux -DryRun   # see jarvis inject --help for exact flags
#   .\scripts\inject.ps1 bundle -Out umbra-inject-bundle.zip
python -m jarvis inject @args
exit $LASTEXITCODE
