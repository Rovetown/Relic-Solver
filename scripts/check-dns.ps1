$ErrorActionPreference = 'SilentlyContinue'

$Domain   = 'iomreliccalc.me'
$WwwHost  = "www.$Domain"
$Asset    = "https://$Domain/static/css/style.min.css"
$NsWanted = @('hassan.ns.cloudflare.com', 'tani.ns.cloudflare.com')

$CfPrefixes = @('104.16.', '104.17.', '104.18.', '104.19.', '104.20.', '104.21.',
                '104.22.', '104.23.', '104.24.', '104.25.', '104.26.', '104.27.',
                '172.64.', '172.65.', '172.66.', '172.67.', '172.68.', '172.69.',
                '162.159.', '188.114.', '198.41.')

$Rows = [System.Collections.Generic.List[object]]::new()

function Add-Row {
    param([string]$Section, [string]$Check, [string]$Expected, [string]$Actual, [bool]$Pass)
    $shown = if ([string]::IsNullOrWhiteSpace($Actual)) { '(no answer)' } else { $Actual }
    $Rows.Add([pscustomobject]@{
        Section  = $Section
        Check    = $Check
        Expected = $Expected
        Actual   = $shown
        Status   = if ($Pass) { 'OK' } else { 'WAIT' }
    })
}

function Resolve-Safe {
    param([string]$Name, [string]$Type, [string]$Server)
    try { Resolve-DnsName -Name $Name -Type $Type -Server $Server -DnsOnly -ErrorAction Stop }
    catch { $null }
}

function Test-CloudflareIp {
    param([string]$Ip)
    foreach ($p in $CfPrefixes) { if ($Ip.StartsWith($p)) { return $true } }
    return $false
}

function Get-Headers {
    param([string]$Url, [switch]$NoRedirect)
    $curlArgs = @('-sS', '-I', '--max-time', '15')
    if (-not $NoRedirect) { $curlArgs += '-L' }
    $curlArgs += $Url
    try { (& curl.exe @curlArgs 2>&1) -join "`n" } catch { '' }
}

function Find-Header {
    param([string]$Blob, [string]$Name)
    $m = [regex]::Match($Blob, "(?im)^$([regex]::Escape($Name)):\s*(.+)$")
    if ($m.Success) { $m.Groups[1].Value.Trim() } else { '' }
}

function Get-Statuses {
    param([string]$Blob)
    @([regex]::Matches($Blob, '(?m)^HTTP/\S+\s+(\d{3})') | ForEach-Object { $_.Groups[1].Value })
}

Write-Host ''
Write-Host "  Cloudflare cutover check - $Domain" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray
Write-Host ''

foreach ($resolver in @(
    @{ Name = 'Google';     Ip = '8.8.8.8' },
    @{ Name = 'Cloudflare'; Ip = '1.1.1.1' },
    @{ Name = 'Quad9';      Ip = '9.9.9.9' }
)) {
    $ns = Resolve-Safe -Name $Domain -Type 'NS' -Server $resolver.Ip
    $names = @($ns | Where-Object { $_.Type -eq 'NS' } | ForEach-Object { $_.NameHost } | Sort-Object)
    $missing = @($NsWanted | Where-Object { $names -notcontains $_ })
    $pass = ($names.Count -ge 2) -and ($missing.Count -eq 0)
    Add-Row 'Delegation' "NS via $($resolver.Name)" 'hassan + tani .ns.cloudflare.com' ($names -join ', ') $pass
}

$soa = Resolve-Safe -Name $Domain -Type 'SOA' -Server $NsWanted[0]
$soaPrimary = @($soa | Where-Object { $_.Type -eq 'SOA' } | ForEach-Object { $_.PrimaryServer })[0]
Add-Row 'Delegation' 'SOA at the zone itself' 'hassan.ns.cloudflare.com' $soaPrimary ($soaPrimary -like '*cloudflare.com')

$ds = Resolve-Safe -Name $Domain -Type 'DS' -Server '1.1.1.1'
$dsKeyTags = @($ds | Where-Object { $_.Type -eq 'DS' } | ForEach-Object { $_.KeyTag })
Add-Row 'Delegation' 'DNSSEC (DS at the registry)' 'a DS record exists' `
        ($dsKeyTags -join ', ') ($dsKeyTags.Count -gt 0)

foreach ($name in @($Domain, $WwwHost)) {
    $a = Resolve-Safe -Name $name -Type 'A' -Server '1.1.1.1'
    $ips = @($a | Where-Object { $_.Type -eq 'A' } | ForEach-Object { $_.IPAddress })
    $bad = @($ips | Where-Object { -not (Test-CloudflareIp $_) })
    $proxied = ($ips.Count -gt 0) -and ($bad.Count -eq 0)
    Add-Row 'Records' "$name resolves to" 'a Cloudflare proxy address' ($ips -join ', ') $proxied
}

$mx = Resolve-Safe -Name $Domain -Type 'MX' -Server '1.1.1.1'
$mxHosts = @($mx | Where-Object { $_.Type -eq 'MX' } | ForEach-Object { $_.NameExchange })
$mxShown = if ($mxHosts.Count) { $mxHosts -join ', ' } else { 'none' }
Add-Row 'Records' 'MX records' 'none - mail is not used' $mxShown ($mxHosts.Count -eq 0)

$txt = Resolve-Safe -Name $Domain -Type 'TXT' -Server '1.1.1.1'
$spf = @($txt | Where-Object { $_.Type -eq 'TXT' } |
         ForEach-Object { $_.Strings -join '' } |
         Where-Object { $_ -like 'v=spf1*' })[0]
Add-Row 'Records' 'SPF' 'v=spf1 -all' $spf ($spf -eq 'v=spf1 -all')

$dmarcAnswer = Resolve-Safe -Name "_dmarc.$Domain" -Type 'TXT' -Server '1.1.1.1'
$dmarc = @($dmarcAnswer | Where-Object { $_.Type -eq 'TXT' } | ForEach-Object { $_.Strings -join '' })[0]
Add-Row 'Records' 'DMARC' 'v=DMARC1; p=reject;' $dmarc ($dmarc -like '*p=reject*')

$gv = Resolve-Safe -Name "thbwocoajmxu.$Domain" -Type 'CNAME' -Server '1.1.1.1'
$gvTarget = @($gv | Where-Object { $_.Type -eq 'CNAME' } | ForEach-Object { $_.NameHost })[0]
Add-Row 'Records' 'Google verification CNAME' 'points at googlehosted.com (DNS only)' $gvTarget ($gvTarget -like '*googlehosted.com')

$apex = Get-Headers "https://$Domain/"

$server = Find-Header $apex 'server'
Add-Row 'HTTP' 'Edge is serving the apex' 'server: cloudflare' $server ($server -match 'cloudflare')

$ray = Find-Header $apex 'cf-ray'
Add-Row 'HTTP' 'Cloudflare ray id (PoP)' 'present, e.g. ...-FRA' $ray ($ray -ne '')

$altsvc = Find-Header $apex 'alt-svc'
Add-Row 'HTTP' 'HTTP/3 offered' 'h3=":443"' $altsvc ($altsvc -match 'h3')

$apexStatus = @(Get-Statuses $apex)[-1]
Add-Row 'HTTP' 'Apex final status' '200' $apexStatus ($apexStatus -eq '200')

$hsts = Find-Header $apex 'strict-transport-security'
Add-Row 'HTTP' 'HSTS header' 'max-age=31536000; includeSubDomains' $hsts ($hsts -match 'max-age=31536000')

$null = Get-Headers $Asset
Start-Sleep -Milliseconds 400
$second = Get-Headers $Asset

$cache = Find-Header $second 'cf-cache-status'
Add-Row 'HTTP' 'Static asset cached at the edge' 'cf-cache-status: HIT' $cache ($cache -eq 'HIT')

$age = Find-Header $second 'age'
Add-Row 'HTTP' 'Edge age header' 'a number of seconds' $age ($age -ne '')

$wwwHead = Get-Headers "https://$WwwHost/" -NoRedirect
$wwwStatus = @(Get-Statuses $wwwHead)[0]
$wwwLoc = Find-Header $wwwHead 'location'
Add-Row 'HTTP' 'www redirects to apex' "308 -> https://$Domain/" ("$wwwStatus $wwwLoc").Trim() `
        (($wwwStatus -eq '308') -and ($wwwLoc -like "https://$Domain*"))

$plain = Get-Headers "http://$Domain/" -NoRedirect
$plainStatus = @(Get-Statuses $plain)[0]
Add-Row 'HTTP' 'Plain HTTP is redirected' '301 or 308' $plainStatus ($plainStatus -in @('301', '308'))

foreach ($section in ($Rows | Group-Object Section)) {
    Write-Host ("  " + $section.Name.ToUpper()) -ForegroundColor Yellow
    Write-Host ('  ' + ('-' * 110)) -ForegroundColor DarkGray
    foreach ($r in $section.Group) {
        $colour = if ($r.Status -eq 'OK') { 'Green' } else { 'Red' }
        Write-Host ('  [{0,-4}] ' -f $r.Status) -ForegroundColor $colour -NoNewline
        Write-Host ('{0,-34}' -f $r.Check) -NoNewline
        Write-Host ('want: {0,-38}' -f $r.Expected) -ForegroundColor DarkGray -NoNewline
        Write-Host ('got: {0}' -f $r.Actual)
    }
    Write-Host ''
}

$waiting = @($Rows | Where-Object { $_.Status -ne 'OK' })
$okCount = @($Rows | Where-Object { $_.Status -eq 'OK' }).Count
Write-Host ("  {0} of {1} checks pass." -f $okCount, $Rows.Count) -ForegroundColor Cyan

if ($waiting.Count) {
    Write-Host ''
    Write-Host '  Still waiting on:' -ForegroundColor Yellow
    foreach ($w in $waiting) { Write-Host ("    - " + $w.Check) }
    Write-Host ''
    Write-Host '  How long each one normally takes:' -ForegroundColor DarkGray
    Write-Host '    NS at one resolver      up to 48h worst case, usually under 1h' -ForegroundColor DarkGray
    Write-Host '    a record edit in a zone 30s to 5 min while TTL is Auto' -ForegroundColor DarkGray
    Write-Host '    a cache or redirect rule under 30s' -ForegroundColor DarkGray
    Write-Host '    first cache HIT         needs one earlier request for the same URL' -ForegroundColor DarkGray
    Write-Host '    a Heroku maintenance 503 will fail every HTTP row until maintenance is off' -ForegroundColor DarkGray
}
Write-Host ''
