param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\run.py" @Arguments
exit $LASTEXITCODE
