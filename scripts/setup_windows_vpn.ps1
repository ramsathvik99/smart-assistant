<#
.SYNOPSIS
    Smart Assistant - Windows Host Native VPN Setup and Control Script
.DESCRIPTION
    Configures and controls the native Windows VPN connection to the Smart Assistant VPS gateway.
    Routes only the private 10.8.0.0/24 subnet (split tunneling) directly to the phone (10.8.0.2).
    Requires zero third-party software installation.
.PARAMETER ServerAddress
    Public IP or domain name of the remote VPN VPS gateway.
.PARAMETER Psk
    Pre-Shared Key matching the VPS and Android phone configuration.
.PARAMETER ConnectionName
    Name of the Windows VPN connection profile (default: SmartAssistantVPN).
.PARAMETER Connect
    Connects to the VPN gateway.
.PARAMETER Disconnect
    Disconnects the active VPN session.
.PARAMETER Status
    Outputs the connection status and route information.
#>

[CmdletBinding()]
param (
    [string]$ServerAddress,
    [string]$Psk,
    [string]$ConnectionName = "SmartAssistantVPN",
    [switch]$Connect,
    [switch]$Disconnect,
    [switch]$Status,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

function Get-VpnState {
    param ([string]$Name)
    $vpn = Get-VpnConnection -Name $Name -ErrorAction SilentlyContinue
    if (-not $vpn) {
        return @{ Exists = $false; Status = "NotConfigured" }
    }
    return @{
        Exists = $true
        Status = $vpn.ConnectionStatus
        ServerAddress = $vpn.ServerAddress
        TunnelType = $vpn.TunnelType
        SplitTunneling = $vpn.SplitTunneling
    }
}

# --- Action: Status ---
if ($Status) {
    $state = Get-VpnState -Name $ConnectionName
    if (-not $state.Exists) {
        [PSCustomObject]@{
            Success = $false
            Configured = $false
            Status = "NotConfigured"
            Message = "VPN profile '$ConnectionName' is not configured."
        } | ConvertTo-Json -Compress
        exit 0
    }

    $isRoutable = $false
    if ($state.Status -eq "Connected") {
        $testPing = Test-Connection -ComputerName "10.8.0.2" -Count 1 -Quiet -ErrorAction SilentlyContinue
        $isRoutable = [bool]$testPing
    }

    [PSCustomObject]@{
        Success = $true
        Configured = $true
        ConnectionName = $ConnectionName
        Status = $state.Status
        ServerAddress = $state.ServerAddress
        TunnelType = $state.TunnelType
        SplitTunneling = $state.SplitTunneling
        PhoneRoutable = $isRoutable
    } | ConvertTo-Json -Compress
    exit 0
}

# --- Action: Disconnect ---
if ($Disconnect) {
    try {
        $rasOutput = rasdial.exe $ConnectionName /disconnect 2>&1
        [PSCustomObject]@{
            Success = $true
            Action = "disconnect"
            Status = "Disconnected"
            Message = "Disconnected VPN session '$ConnectionName'."
        } | ConvertTo-Json -Compress
        exit 0
    } catch {
        [PSCustomObject]@{
            Success = $false
            Action = "disconnect"
            Error = $_.Exception.Message
        } | ConvertTo-Json -Compress
        exit 1
    }
}

# --- Action: Remove ---
if ($Remove) {
    try {
        rasdial.exe $ConnectionName /disconnect 2>&1 | Out-Null
        Remove-VpnConnection -Name $ConnectionName -Force -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            Success = $true
            Action = "remove"
            Message = "Removed VPN profile '$ConnectionName'."
        } | ConvertTo-Json -Compress
        exit 0
    } catch {
        [PSCustomObject]@{
            Success = $false
            Action = "remove"
            Error = $_.Exception.Message
        } | ConvertTo-Json -Compress
        exit 1
    }
}

# --- Action: Connect ---
if ($Connect) {
    $state = Get-VpnState -Name $ConnectionName
    if (-not $state.Exists) {
        [PSCustomObject]@{
            Success = $false
            Error = "VPN profile '$ConnectionName' does not exist. Run configuration first."
        } | ConvertTo-Json -Compress
        exit 1
    }

    if ($state.Status -eq "Connected") {
        [PSCustomObject]@{
            Success = $true
            Status = "Connected"
            Message = "VPN session '$ConnectionName' is already connected."
        } | ConvertTo-Json -Compress
        exit 0
    }

    try {
        # Username and password use smart-assistant-laptop and the PSK
        $user = "smart-assistant-laptop"
        $rasOutput = rasdial.exe $ConnectionName $user $Psk 2>&1
        $exitCode = $LASTEXITCODE

        $newState = Get-VpnState -Name $ConnectionName
        if ($newState.Status -eq "Connected" -or $exitCode -eq 0) {
            [PSCustomObject]@{
                Success = $true
                Status = "Connected"
                Message = "Connected successfully to VPN gateway."
            } | ConvertTo-Json -Compress
            exit 0
        } else {
            [PSCustomObject]@{
                Success = $false
                Status = $newState.Status
                ExitCode = $exitCode
                Error = ($rasOutput -join "`n")
            } | ConvertTo-Json -Compress
            exit 1
        }
    } catch {
        [PSCustomObject]@{
            Success = $false
            Error = $_.Exception.Message
        } | ConvertTo-Json -Compress
        exit 1
    }
}

# --- Action: Configure Profile ---
if (-not $ServerAddress -or -not $Psk) {
    [PSCustomObject]@{
        Success = $false
        Error = "ServerAddress and Psk are required to configure the VPN profile."
    } | ConvertTo-Json -Compress
    exit 1
}

try {
    # Remove existing profile if present to ensure clean state
    $existing = Get-VpnConnection -Name $ConnectionName -ErrorAction SilentlyContinue
    if ($existing) {
        rasdial.exe $ConnectionName /disconnect 2>&1 | Out-Null
        Remove-VpnConnection -Name $ConnectionName -Force -ErrorAction SilentlyContinue
    }

    # Add native L2TP/IPSec VPN connection with Split Tunneling
    Add-VpnConnection -Name $ConnectionName `
        -ServerAddress $ServerAddress `
        -TunnelType L2tp `
        -L2tpPsk $Psk `
        -AuthenticationMethod MSChapv2 `
        -SplitTunneling `
        -RememberCredential `
        -Force

    # Add route for the private phone tunnel subnet (10.8.0.0/24)
    Add-VpnConnectionRoute -ConnectionName $ConnectionName `
        -DestinationPrefix "10.8.0.0/24" `
        -RouteMetric 10 `
        -ErrorAction SilentlyContinue

    [PSCustomObject]@{
        Success = $true
        Action = "configure"
        ConnectionName = $ConnectionName
        ServerAddress = $ServerAddress
        TunnelType = "L2tp"
        TargetSubnet = "10.8.0.0/24"
        PhoneDestination = "10.8.0.2"
        Message = "Windows native VPN configured successfully for '$ConnectionName' with split tunneling (10.8.0.0/24)."
    } | ConvertTo-Json -Compress
    exit 0
} catch {
    [PSCustomObject]@{
        Success = $false
        Action = "configure"
        Error = $_.Exception.Message
    } | ConvertTo-Json -Compress
    exit 1
}
