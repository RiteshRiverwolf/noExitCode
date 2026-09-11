<#
Stage 0 offline phase: does AnythingLLM keep working with no route out, and
what does it try to reach? Every outbound attempt is recorded with a packet
capture we control, not taken from AnythingLLM's own logs.

Mechanism (container-scoped; nothing on the Windows host is changed):
  - A netshoot sidecar shares the AnythingLLM container's network namespace.
  - iptables in that namespace allows only loopback, replies to inbound
    connections, and TCP to the host's Ollama (11434) and MCP tool (8765).
    Everything else is dropped and counted.
  - tcpdump in the same namespace captures all traffic on every interface
    into results/stage0/pcap/.

Windows, kept separate (ARCHITECTURE section 8.2):
  A.  Canary: the container deliberately tries to reach example.com.
      Expected: blocked; visible in capture A and the DROP counter.
  B2. The real task: language data pre-seeded (the fix), full integration
      test with egress blocked. Expected: passes; capture B2 shows no
      external connection attempts.
  B1. OCR with no cached language data (runs LAST): the online run downloaded
      eng.traineddata on first use. It is moved aside, then a scan is uploaded
      with egress blocked. This is what a fresh air-gapped install would hit.
      Offline run 1 showed it crashes the whole container, so it goes last.

Name resolution (checked 2026-09-11 on this machine):
  - The container is on Docker's default bridge, so DNS goes to Docker
    Desktop's resolver at 192.168.65.7 over eth0 -- not a loopback resolver.
    The policy therefore blocks DNS too; queried names still show in the
    capture as dropped packets.
  - host.docker.internal is NOT in the container's /etc/hosts; it only
    resolves through that DNS server, and to an IPv6 address first. So for the
    test windows its IPv4 address is pinned in /etc/hosts (restored at the end)
    instead of opening DNS.
  - The container has no IPv6 address or route; ip6tables drops everything
    but loopback anyway, as a guard.

Scope, stated honestly:
  - This observes the container's own traffic, not the Windows host's.
  - The Windows host processes (Ollama, the MCP tool) are only sampled once a
    second for non-loopback connections -- weaker evidence than a capture.
  - A cold offline *start* is not covered: restarting the container creates a
    fresh network namespace without these rules. Startup downloads are
    identified from AnythingLLM's source instead (see NOTES.md).
  - If B1's OCR still succeeds, the language data is cached somewhere other
    than the storage folder, and the dependency is not disproven.

Run:  & "C:\SIH 2026\stage0\offline_phase.ps1"
#>

$ErrorActionPreference = "Continue"
$root    = "C:\SIH 2026"
$ctr     = "anythingllm-stage0"
$img     = "nicolaka/netshoot:latest"
$out     = "$root\results\stage0"
$pcap    = "$out\pcap"
$summary = "$out\offline_summary.txt"
$td      = "$root\stage0\anythingllm\models\tesseract\eng.traineddata"
$tdAside = "$td.aside"
New-Item -ItemType Directory -Force -Path $pcap | Out-Null
"Stage 0 offline phase - $(Get-Date -Format o)" | Set-Content $summary

function Say([string]$msg) { $msg | Tee-Object -FilePath $summary -Append }
function InNetns([string]$script) {
    docker run --rm --net "container:$ctr" --cap-add NET_ADMIN $img sh -c $script 2>&1 |
        Tee-Object -FilePath $summary -Append
}
# Two captures per window. Packets dropped in OUTPUT never reach an interface,
# so "-i any" only sees traffic that was allowed; the NFLOG rule in front of
# DROP copies every blocked packet to nflog:5, captured as <name>_dropped.pcap.
function Start-Capture([string]$name) {
    $sh = 'tcpdump -i any -nn -U -w /pcap/NAME.pcap & a=$!; tcpdump -i nflog:5 -nn -U -w /pcap/NAME_dropped.pcap & b=$!; trap ''kill $a $b'' TERM; wait' -replace 'NAME', $name
    docker run -d --name "stage0-cap-$name" --net "container:$ctr" `
        --cap-add NET_ADMIN --cap-add NET_RAW -v "${pcap}:/pcap" $img `
        sh -c $sh | Out-Null
    Start-Sleep -Seconds 2
}
function Stop-Capture([string]$name) {
    Start-Sleep -Seconds 2
    docker stop "stage0-cap-$name" | Out-Null
    docker rm "stage0-cap-$name" | Out-Null
}
function Invoke-Harness([string]$label, [string]$mode, [string]$uploadTimeout) {
    $env:STAGE0_LABEL = $label
    $env:STAGE0_MODE = $mode
    $env:STAGE0_UPLOAD_TIMEOUT = $uploadTimeout
    & "$root\.venv\Scripts\python.exe" -u "$root\stage0\run_integration_test.py" 2>&1 |
        Tee-Object -FilePath "$out\run_${label}_console.log"
    Remove-Item Env:STAGE0_MODE, Env:STAGE0_UPLOAD_TIMEOUT -ErrorAction SilentlyContinue
}

# --- setup ------------------------------------------------------------------
# IPv4 only: plain `getent hosts` returns the IPv6 address first, which the
# IPv4 allow rules below cannot use.
$hostIp = ((docker exec $ctr getent ahostsv4 host.docker.internal | Select-Object -First 1) -split '\s+')[0]
if ($hostIp -notmatch '^\d+\.\d+\.\d+\.\d+$') { Say "could not resolve host.docker.internal to IPv4 (got '$hostIp'); aborting"; exit 1 }
Say "host.docker.internal resolves to $hostIp (IPv4) inside the container"

# Pin it, so the container can still find Ollama and the MCP tool once DNS is blocked.
docker exec -u root $ctr sh -c "cp /etc/hosts /tmp/hosts.stage0 && echo '$hostIp host.docker.internal' >> /etc/hosts"
Say "pinned in /etc/hosts: $hostIp host.docker.internal"

$ipt = (docker run --rm --net "container:$ctr" --cap-add NET_ADMIN $img sh -c `
    "iptables -L -n >/dev/null 2>&1 && echo iptables || echo iptables-legacy").Trim()
Say "iptables backend: $ipt"

Say "`n== egress policy applied =="
InNetns @"
$ipt -N STAGE0_EGRESS 2>/dev/null || $ipt -F STAGE0_EGRESS
$ipt -A STAGE0_EGRESS -o lo -j ACCEPT
$ipt -A STAGE0_EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
$ipt -A STAGE0_EGRESS -p tcp -d $hostIp --dport 11434 -j ACCEPT
$ipt -A STAGE0_EGRESS -p tcp -d $hostIp --dport 8765 -j ACCEPT
$ipt -A STAGE0_EGRESS -j NFLOG --nflog-group 5 --nflog-prefix S0DROP
$ipt -A STAGE0_EGRESS -j DROP
$ipt -C OUTPUT -j STAGE0_EGRESS 2>/dev/null || $ipt -I OUTPUT 1 -j STAGE0_EGRESS
$ipt -L STAGE0_EGRESS -v -n -x
ip6tables -N STAGE0_EGRESS6 2>/dev/null || ip6tables -F STAGE0_EGRESS6
ip6tables -A STAGE0_EGRESS6 -o lo -j ACCEPT
ip6tables -A STAGE0_EGRESS6 -j NFLOG --nflog-group 5 --nflog-prefix S0DROP6
ip6tables -A STAGE0_EGRESS6 -j DROP
ip6tables -C OUTPUT -j STAGE0_EGRESS6 2>/dev/null || ip6tables -I OUTPUT 1 -j STAGE0_EGRESS6
"@

# --- window A: canary -------------------------------------------------------
# curl's exit code tells the outcome apart: 0 = reached, 6 = name lookup
# failed, 7 = refused, 28 = timed out (packets silently dropped).
Say "`n== window A: canary =="
Start-Capture "A_canary"
$ext = docker exec $ctr sh -c "curl -s -m 8 -o /dev/null https://example.com; echo exit=`$?"
Say "container -> https://example.com (by name) : $ext   (expected: exit=6 or 28)"
$extIp = docker exec $ctr sh -c "curl -s -m 8 -o /dev/null https://1.1.1.1; echo exit=`$?"
Say "container -> https://1.1.1.1 (by IP)       : $extIp   (expected: exit=28)"
$loc = docker exec $ctr curl -s -m 8 -o /dev/null -w '%{http_code}' "http://host.docker.internal:11434/api/tags"
Say "container -> host Ollama                   : $loc   (expected: 200)"
$mcp = docker exec $ctr curl -s -m 8 -o /dev/null -w '%{http_code}' "http://host.docker.internal:8765/mcp"
Say "container -> host MCP tool                 : $mcp   (expected: 400 or 406, i.e. reached)"
Stop-Capture "A_canary"
Say "`n-- DROP counter, window A --"
InNetns "$ipt -L STAGE0_EGRESS -v -n -x; $ipt -Z STAGE0_EGRESS"

# --- window B2: the real task, language data pre-seeded ---------------------
Say "`n== window B2: full task with egress blocked, language data pre-seeded =="
$mcpPid = (Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
$hostLog = "$out\offline_host_samples.log"
"" | Set-Content $hostLog
$job = Start-Job -ArgumentList $mcpPid, $hostLog -ScriptBlock {
    param($mcpPid, $log)
    while ($true) {
        # Re-read each second: Ollama starts a separate runner process per
        # loaded model, which the listening server's PID alone would miss.
        $ids = @($mcpPid) + @(Get-Process -Name ollama* -ErrorAction SilentlyContinue | ForEach-Object Id)
        Get-NetTCPConnection -ErrorAction SilentlyContinue |
            Where-Object { $_.OwningProcess -in $ids -and $_.RemoteAddress -notin '127.0.0.1', '::1', '0.0.0.0', '::' } |
            ForEach-Object { "$(Get-Date -Format o) pid=$($_.OwningProcess) remote=$($_.RemoteAddress):$($_.RemotePort) state=$($_.State)" } |
            Add-Content $log
        Start-Sleep -Seconds 1
    }
}
Start-Capture "B2_task"
Invoke-Harness "offline" "full" "600"
Stop-Capture "B2_task"
Stop-Job $job
Remove-Job $job
Say "`n-- DROP counter, window B2 --"
InNetns "$ipt -L STAGE0_EGRESS -v -n -x; $ipt -Z STAGE0_EGRESS"

# --- window B1: OCR with no cached language data (runs last) ----------------
# Offline run 1 (2026-09-11) showed this crashes the whole container: the
# failed download throws an uncaught error in tesseract.js. So it goes last.
Say "`n== window B1: scan upload with eng.traineddata moved aside =="
if (Test-Path $td) { Move-Item $td $tdAside -Force; Say "moved aside: $td" } else { Say "no cached eng.traineddata found" }
Start-Capture "B1_ocr_nocache"
Invoke-Harness "offline-nocache" "upload-only" "180"
Start-Sleep -Seconds 3
$state = docker inspect $ctr --format "status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} finished={{.State.FinishedAt}}"
Say "container after B1: $state"
if ($state -notmatch 'status=running') {
    Say "-- last container log lines --"
    docker logs $ctr --tail 15 2>&1 | Tee-Object -FilePath $summary -Append
}
Stop-Capture "B1_ocr_nocache"
if (Test-Path $tdAside) { Move-Item $tdAside $td -Force; Say "restored: $td" }
Say "`n-- DROP counter, window B1 --"
InNetns "$ipt -L STAGE0_EGRESS -v -n -x"

# --- analysis ---------------------------------------------------------------
foreach ($n in "A_canary", "A_canary_dropped", "B2_task", "B2_task_dropped", "B1_ocr_nocache", "B1_ocr_nocache_dropped") {
    Say "`n== capture ${n}: DNS names queried =="
    docker run --rm -v "${pcap}:/pcap" $img sh -c "tshark -r /pcap/$n.pcap -Y 'dns.flags.response == 0' -T fields -e dns.qry.name 2>/dev/null | sort | uniq -c | sort -rn" 2>&1 |
        Tee-Object -FilePath $summary -Append
    Say "== capture ${n}: new outbound TCP connections (SYN) by destination =="
    docker run --rm -v "${pcap}:/pcap" $img sh -c "tshark -r /pcap/$n.pcap -Y 'tcp.flags.syn == 1 && tcp.flags.ack == 0' -T fields -e ip.dst -e tcp.dstport 2>/dev/null | sort | uniq -c | sort -rn" 2>&1 |
        Tee-Object -FilePath $summary -Append
    Say "== capture ${n}: non-DNS UDP by destination =="
    docker run --rm -v "${pcap}:/pcap" $img sh -c "tshark -r /pcap/$n.pcap -Y 'udp && !dns' -T fields -e ip.dst -e udp.dstport 2>/dev/null | sort | uniq -c | sort -rn" 2>&1 |
        Tee-Object -FilePath $summary -Append
}

Say "`n== Windows host: non-loopback connections by Ollama / MCP tool during window B2 =="
$samples = Get-Content $hostLog | Where-Object { $_.Trim() }
if ($samples) { $samples | Sort-Object -Unique | ForEach-Object { Say $_ } } else { Say "(none recorded)" }

# --- restore ----------------------------------------------------------------
Say "`n== egress policy removed; container back to normal networking =="
InNetns "$ipt -D OUTPUT -j STAGE0_EGRESS; $ipt -F STAGE0_EGRESS; $ipt -X STAGE0_EGRESS; ip6tables -D OUTPUT -j STAGE0_EGRESS6; ip6tables -F STAGE0_EGRESS6; ip6tables -X STAGE0_EGRESS6; echo removed"
docker exec -u root $ctr sh -c "cat /tmp/hosts.stage0 > /etc/hosts && rm /tmp/hosts.stage0 && echo '/etc/hosts restored'" 2>&1 |
    Tee-Object -FilePath $summary -Append

Say "`nDone. Summary: $summary"
