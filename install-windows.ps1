# Install or update a Fusion add-in from github.com/nvdberg/fusion-addins (Windows).
#
#   Easiest: open PowerShell (Start > type PowerShell) and paste
#     irm https://raw.githubusercontent.com/nvdberg/fusion-addins/main/install-windows.ps1 | iex
#   (for RotaryUnwrap:  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/nvdberg/fusion-addins/main/install-windows.ps1))) RotaryUnwrap )
#   Or double-click "Install on Windows.cmd" in the unzipped download.
#
# It copies the add-in into Fusion's own add-in folder, where Fusion finds it and starts it by itself.
# An update keeps your own files (drawer presets, last settings). Nothing else is changed.
& {
    $ErrorActionPreference = 'Stop'
    $Repo = 'nvdberg/fusion-addins'
    $AddIns = $env:FUSION_ADDINS_DIR
    if (-not $AddIns) { $AddIns = Join-Path $env:APPDATA 'Autodesk\Autodesk Fusion 360\API\AddIns' }
    $Keep = @('*_presets.json', '*_last.json', 'update_seen.json')   # the user's own files, kept on update

    $Here = $PSScriptRoot
    $Name = ''
    if ($args.Count -gt 0) { $Name = [string]$args[0] }
    if (-not $Name -and $Here) {                     # double-clicked next to an unzipped add-in folder
        $m = Get-ChildItem -LiteralPath $Here -Directory |
             Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ($_.Name + '.manifest')) } |
             Select-Object -First 1
        if ($m) { $Name = $m.Name }
    }
    if (-not $Name) { $Name = 'NMJoinery' }
    if ($Name -notmatch '^[A-Za-z]+$') { Write-Host "Unknown add-in name: $Name"; return }

    Write-Host "== Installing $Name into Fusion"
    $Tmp = Join-Path ([IO.Path]::GetTempPath()) ('fusion-addin-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Tmp | Out-Null
    try {
        $Src = ''
        if ($Here -and (Test-Path -LiteralPath (Join-Path $Here "$Name\$Name.manifest"))) { $Src = Join-Path $Here $Name }
        if (-not $Src) {
            Write-Host '   looking for the newest release on GitHub ...'
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            $rels = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases?per_page=50" -Headers @{ 'User-Agent' = 'fusion-addin-installer' }
            $asset = $rels | ForEach-Object { $_.assets } | Where-Object { $_.name -match ('^' + $Name + '-[0-9.]+\.zip$') } | Select-Object -First 1
            if (-not $asset) { Write-Host "No $Name release found on github.com/$Repo"; return }
            Write-Host "   downloading $($asset.name)"
            $zip = Join-Path $Tmp 'addin.zip'
            Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
            Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $Tmp 'x')
            $Src = Join-Path $Tmp "x\$Name"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $Src "$Name.manifest"))) { Write-Host "No $Name folder with $Name.manifest found"; return }

        # put the new version together first, with the user's own files from the old one
        $New = Join-Path $Tmp 'new'
        Copy-Item -LiteralPath $Src -Destination $New -Recurse
        Get-ChildItem -LiteralPath $New -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
        $Dest = Join-Path $AddIns $Name
        $kept = 0
        if (Test-Path -LiteralPath $Dest) {
            foreach ($k in $Keep) {
                foreach ($f in Get-ChildItem -LiteralPath $Dest -Filter $k -File) { Copy-Item -LiteralPath $f.FullName -Destination $New; $kept++ }
            }
            Remove-Item -LiteralPath $Dest -Recurse -Force
        }
        New-Item -ItemType Directory -Path $AddIns -Force | Out-Null
        Copy-Item -LiteralPath $New -Destination $Dest -Recurse
        Get-ChildItem -LiteralPath $Dest -Recurse -File | Unblock-File

        $ver = (Get-Content -LiteralPath (Join-Path $Dest "$Name.manifest") -Raw | ConvertFrom-Json).version
        Write-Host "== Done: $Name $ver is in Fusion's add-in folder"
        if ($kept) { Write-Host "   kept $kept of your own file(s) (presets / last settings)" }
        if (Get-Process -Name 'Fusion360' -ErrorAction SilentlyContinue) {
            Write-Host '   Fusion is open: quit and restart it to load this version.'
        } else {
            Write-Host "   Start Fusion: $Name starts by itself."
        }
        Write-Host "   (Check: Utilities > Add-ins > Scripts and Add-Ins: $Name with Run on and Run on Startup ticked.)"
    } finally {
        Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
} @args
