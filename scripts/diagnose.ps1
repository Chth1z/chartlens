$ErrorActionPreference = "Continue"
Write-Host "Python:"
python --version
Write-Host "Node:"
node --version
Write-Host "Backend health:"
try { Invoke-WebRequest http://127.0.0.1:8000/api/health -UseBasicParsing | Select-Object -ExpandProperty Content } catch { $_.Exception.Message }
Write-Host "OCR sidecar health:"
try { Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing | Select-Object -ExpandProperty Content } catch { $_.Exception.Message }
Write-Host "Frontend:"
try { Invoke-WebRequest http://127.0.0.1:5173 -UseBasicParsing | Select-Object -ExpandProperty StatusCode } catch { $_.Exception.Message }
