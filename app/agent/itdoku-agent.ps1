<#
.SYNOPSIS
  IT-Dokumentation – Agent für Windows (Windows PowerShell 5.1 oder PowerShell 7).

.DESCRIPTION
  Sammelt Hardware, System, Datenträger, Netzwerk, installierte Software, Updates und Dienste und schickt sie per HTTPS
  an die IT-Dokumentation. Keine Zusatzmodule nötig.

  Einrichten (als Administrator):
    powershell -ExecutionPolicy Bypass -File itdoku-agent.ps1 -Install -Url https://doku.example.de -Token itd_...
  Einmal melden:   powershell -ExecutionPolicy Bypass -File "C:\ProgramData\ITDoku\itdoku-agent.ps1" -Run
  Nur ansehen:     powershell -ExecutionPolicy Bypass -File itdoku-agent.ps1 -Print
  Entfernen:       powershell -ExecutionPolicy Bypass -File "C:\ProgramData\ITDoku\itdoku-agent.ps1" -Uninstall

  Geplante Aufgabe „ITDoku Agent“ als SYSTEM: täglich und 2 Minuten nach dem Start.
  Konfiguration: C:\ProgramData\ITDoku\config.json (nur SYSTEM und Administratoren).
#>
[CmdletBinding()]
param(
  [switch]$Install,
  [switch]$Uninstall,
  [switch]$Run,
  [switch]$Print,
  [string]$Url,
  [string]$Token,
  [switch]$AllowHttp,
  [switch]$Insecure,
  [switch]$SkipUpdateSearch
)

$ErrorActionPreference = 'Stop'
$AgentVersion = '1.0'
$Dir = Join-Path $env:ProgramData 'ITDoku'
$ConfFile = Join-Path $Dir 'config.json'
$ScriptFile = Join-Path $Dir 'itdoku-agent.ps1'
$TaskName = 'ITDoku Agent'

function Part([scriptblock]$Block, $Default) {
  # Ein kaputter Teil darf den Bericht nicht verhindern
  try { & $Block } catch { $Default }
}

function IsoUtc($Date) {
  if (-not $Date) { return '' }
  try { return ([datetime]$Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') } catch { return '' }
}

function Get-OsInfo {
  $os = Get-CimInstance Win32_OperatingSystem
  $cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction SilentlyContinue
  $display = $cv.DisplayVersion
  if (-not $display) { $display = $cv.ReleaseId }
  $build = $os.BuildNumber
  if ($cv.UBR) { $build = "$($os.BuildNumber).$($cv.UBR)" }
  $name = ($os.Caption -replace '^Microsoft\s+', '').Trim()
  # Windows 11 meldet sich in der Caption korrekt; ältere Builds von 11 heißen im Registry-Namen noch „Windows 10“
  @{ name = $name; version = "$display"; build = "$build"; arch = $os.OSArchitecture; kernel = $os.Version;
     installed_on = (IsoUtc $os.InstallDate) }
}

function Get-HwInfo {
  $cs = Get-CimInstance Win32_ComputerSystem
  $bios = Get-CimInstance Win32_BIOS
  $cpu = @(Get-CimInstance Win32_Processor)
  $enc = Get-CimInstance Win32_SystemEnclosure -ErrorAction SilentlyContinue
  $types = @($enc.ChassisTypes)
  $chassis = 'desktop'
  if ($types | Where-Object { $_ -in 8, 9, 10, 14, 30, 31, 32 }) { $chassis = 'laptop' }
  if ($types | Where-Object { $_ -in 17, 23, 28, 29 }) { $chassis = 'server' }
  $virtual = ($cs.Model -match 'Virtual|VMware|KVM|QEMU|HVM|Bochs') -or ($cs.Manufacturer -match 'VMware|QEMU|Xen|innotek|Parallels')
  if ($virtual) { $chassis = 'vm' }
  $serial = $bios.SerialNumber
  @{ manufacturer = $cs.Manufacturer; model = $cs.Model; serial = "$serial"; cpu = ($cpu[0].Name -replace '\s+', ' ').Trim();
     cores = ($cpu | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum;
     ram_mb = [int64]([math]::Round($cs.TotalPhysicalMemory / 1MB)); chassis = $chassis; virtual = [bool]$virtual;
     bios = "$($bios.Manufacturer) $($bios.SMBIOSBIOSVersion)".Trim() }
}

function Get-Disks {
  @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object { $_.Size } | ForEach-Object {
    @{ mount = $_.DeviceID; fs = $_.FileSystem; label = $_.VolumeName;
       total_gb = [math]::Round($_.Size / 1e9, 1); free_gb = [math]::Round($_.FreeSpace / 1e9, 1) }
  })
}

function Get-Net {
  $ifs = @(); $gw = @(); $dns = @()
  foreach ($a in Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True') {
    $v4 = @($a.IPAddress | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' })
    $v6 = @($a.IPAddress | Where-Object { $_ -match ':' -and $_ -notmatch '^fe80' })
    $ifs += @{ name = $a.Description; mac = $a.MACAddress; ipv4 = $v4; ipv6 = $v6 }
    foreach ($g in @($a.DefaultIPGateway)) { if ($g -and $gw -notcontains $g) { $gw += $g } }
    foreach ($d in @($a.DNSServerSearchOrder)) { if ($d -and $dns -notcontains $d) { $dns += $d } }
  }
  @{ interfaces = $ifs; gateway = $gw; dns = $dns }
}

function Get-Software {
  $keys = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')
  $seen = @{}
  $out = @()
  foreach ($k in $keys) {
    foreach ($p in Get-ItemProperty $k -ErrorAction SilentlyContinue) {
      if (-not $p.DisplayName -or $p.SystemComponent -eq 1 -or $p.ParentKeyName -or $p.ReleaseType -in 'Update', 'Hotfix', 'Security Update') { continue }
      $key = "$($p.DisplayName)|$($p.DisplayVersion)"
      if ($seen.ContainsKey($key)) { continue }
      $seen[$key] = 1
      $inst = ''
      if ("$($p.InstallDate)" -match '^(\d{4})(\d{2})(\d{2})$') { $inst = "$($Matches[1])-$($Matches[2])-$($Matches[3])" }
      $out += @{ name = "$($p.DisplayName)"; version = "$($p.DisplayVersion)"; publisher = "$($p.Publisher)"; installed_on = $inst }
    }
  }
  $out
}

function Get-Updates {
  $res = @{ pending = $null; security = $null; items = @(); reboot_required = $false; last_installed = ''; error = '' }
  $res.reboot_required = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or
                         (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending')
  $hf = Get-HotFix -ErrorAction SilentlyContinue | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn -Descending | Select-Object -First 1
  if ($hf) { $res.last_installed = ([datetime]$hf.InstalledOn).ToString('yyyy-MM-dd') }
  try {
    $session = New-Object -ComObject Microsoft.Update.Session
    $hist = $session.CreateUpdateSearcher()
    $n = $hist.GetTotalHistoryCount()
    if ($n -gt 0) {
      $last = $hist.QueryHistory(0, [math]::Min($n, 50)) | Where-Object { $_.ResultCode -eq 2 } | Sort-Object Date -Descending | Select-Object -First 1
      if ($last -and (-not $res.last_installed -or $last.Date.ToString('yyyy-MM-dd') -gt $res.last_installed)) {
        $res.last_installed = $last.Date.ToString('yyyy-MM-dd')
      }
    }
    if (-not $SkipUpdateSearch) {
      $found = $hist.Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
      $items = @($found.Updates | ForEach-Object { $_.Title })
      $res.pending = $items.Count
      $res.security = @($found.Updates | Where-Object { $_.MsrcSeverity }).Count
      $res.items = @($items | Select-Object -First 300)
    }
  } catch {
    $res.error = "Windows Update nicht abfragbar: $($_.Exception.Message)"
  }
  $res
}

function Get-Services {
  @(Get-CimInstance Win32_Service | ForEach-Object {
    $state = switch ($_.State) { 'Running' { 'running' } 'Stopped' { 'stopped' } default { 'other' } }
    $start = switch ($_.StartMode) { 'Auto' { 'auto' } 'Manual' { 'manual' } 'Disabled' { 'disabled' } default { '' } }
    # Dienste mit „Automatisch (verzögert)“, die sich nach getaner Arbeit selbst beenden, gelten nicht als Fehler
    if ($start -eq 'auto' -and $state -eq 'stopped' -and $_.ExitCode -eq 0 -and $_.Name -match '^(gupdate|edgeupdate|sppsvc|RemoteRegistry|MapsBroker|tiledatamodelsvc|TrustedInstaller|wuauserv|BITS|CDPSvc|WbioSrvc|sppsvc|ShellHWDetection|GoogleUpdater.*|MicrosoftEdgeElevationService|clr_optimization.*|DoSvc|UsoSvc|WaaSMedicSvc)$') { $start = 'manual' }
    @{ name = $_.Name; display = $_.DisplayName; state = $state; start = $start }
  })
}

function Get-Report {
  $os = Get-CimInstance Win32_OperatingSystem
  $cs = Get-CimInstance Win32_ComputerSystem
  $user = Part { $cs.UserName } ''
  @{
    agent_version = $AgentVersion
    platform = 'windows'
    hostname = $env:COMPUTERNAME
    domain = $(if ($cs.PartOfDomain) { $cs.Domain } else { '' })
    logged_in_user = "$user"
    boot_time = (IsoUtc $os.LastBootUpTime)
    os = (Part { Get-OsInfo } @{})
    hardware = (Part { Get-HwInfo } @{})
    disks = @(Part { Get-Disks } @())
    network = (Part { Get-Net } @{})
    software = @(Part { Get-Software } @())
    updates = (Part { Get-Updates } @{})
    services = @(Part { Get-Services } @())
  }
}

function Assert-Admin {
  $id = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not $id.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Bitte in einer PowerShell als Administrator ausführen.'
  }
}

function Test-AgentUrl([string]$U) {
  if ($U -notmatch '^https?://[^/\s]+') { throw "Ungültige Adresse: $U" }
  if ($U -match '^http://' -and -not $AllowHttp) {
    throw 'Unverschlüsselte Adresse (http://). Nur im VPN/LAN sinnvoll – dann mit -AllowHttp bestätigen.'
  }
  $U.TrimEnd('/')
}

function Send-Report($Conf, $Report) {
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  if ($Conf.insecure) {
    if ($PSVersionTable.PSVersion.Major -lt 6) {
      [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
    }
  }
  $body = [Text.Encoding]::UTF8.GetBytes(($Report | ConvertTo-Json -Depth 6 -Compress))
  $params = @{ Uri = "$($Conf.url)/api/agent/v1/report"; Method = 'Post'; Body = $body; ContentType = 'application/json; charset=utf-8';
               Headers = @{ Authorization = "Bearer $($Conf.token)" }; UserAgent = "itdoku-agent/$AgentVersion"; TimeoutSec = 120 }
  if ($Conf.insecure -and $PSVersionTable.PSVersion.Major -ge 6) { $params.SkipCertificateCheck = $true }
  if ($PSVersionTable.PSVersion.Major -lt 6) { $params.UseBasicParsing = $true }
  $last = $null
  for ($i = 1; $i -le 3; $i++) {
    try {
      return Invoke-RestMethod @params
    } catch {
      $code = $null
      try { $code = [int]$_.Exception.Response.StatusCode } catch { }
      if ($code -in 400, 401, 403, 413) { throw "Abgelehnt ($code): $($_.ErrorDetails.Message)" }
      $last = $_.Exception.Message
      Start-Sleep -Seconds (10 * $i)
    }
  }
  throw "Senden fehlgeschlagen: $last"
}

function Read-Conf {
  if (-not (Test-Path $ConfFile)) { throw "Keine Konfiguration in $ConfFile – zuerst mit -Install -Url … -Token … einrichten." }
  Get-Content $ConfFile -Raw | ConvertFrom-Json
}

function Install-Agent {
  Assert-Admin
  if (-not $Url -or -not $Token) { throw '-Install braucht -Url und -Token.' }
  if ($Token -notmatch '^itd_') { throw 'Der Schlüssel beginnt mit itd_ – bitte aus der IT-Dokumentation kopieren.' }
  $conf = @{ url = (Test-AgentUrl $Url); token = $Token.Trim(); insecure = [bool]$Insecure }
  New-Item -ItemType Directory -Path $Dir -Force | Out-Null
  # Ordner nur für SYSTEM und Administratoren (der Schlüssel liegt darin)
  $acl = New-Object Security.AccessControl.DirectorySecurity
  $acl.SetAccessRuleProtection($true, $false)
  foreach ($sid in 'S-1-5-18', 'S-1-5-32-544') {
    $acct = (New-Object Security.Principal.SecurityIdentifier $sid)
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule $acct, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
  }
  Set-Acl -Path $Dir -AclObject $acl
  $conf | ConvertTo-Json | Set-Content -Path $ConfFile -Encoding UTF8
  if ($PSCommandPath -and ((Resolve-Path $PSCommandPath).Path -ne $ScriptFile)) { Copy-Item -Path $PSCommandPath -Destination $ScriptFile -Force }
  $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptFile`" -Run"
  $daily = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(9).AddMinutes((Get-Random -Maximum 480)))
  $boot = New-ScheduledTaskTrigger -AtStartup
  $boot.Delay = 'PT2M'
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
  $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($daily, $boot) -Settings $settings -Principal $principal -Force | Out-Null
  Write-Host "Eingerichtet: geplante Aufgabe '$TaskName' (täglich und nach dem Start)."
  Write-Host 'Erster Bericht wird gesammelt – die Suche nach Windows-Updates kann ein paar Minuten dauern …'
  $res = Send-Report $conf (Get-Report)
  $neu = ''
  if ($res.created) { $neu = ' (neu angelegt)' }
  Write-Host "Erster Bericht gesendet – Gerät #$($res.device_id) in der IT-Dokumentation$neu."
}

function Uninstall-Agent {
  Assert-Admin
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Remove-Item -Path $Dir -Recurse -Force -ErrorAction SilentlyContinue
  Write-Host 'Agent entfernt. Den Agenten in der IT-Dokumentation bitte unter Verwaltung → Agenten löschen oder sperren.'
}

if ($Print) {
  Get-Report | ConvertTo-Json -Depth 6
} elseif ($Install) {
  Install-Agent
} elseif ($Uninstall) {
  Uninstall-Agent
} elseif ($Run) {
  if ($Url -and $Token) { $conf = @{ url = (Test-AgentUrl $Url); token = $Token.Trim(); insecure = [bool]$Insecure } } else { $conf = Read-Conf }
  $res = Send-Report $conf (Get-Report)
  Write-Host "Bericht gesendet (Gerät #$($res.device_id))."
} else {
  Get-Help $PSCommandPath -Detailed
}
