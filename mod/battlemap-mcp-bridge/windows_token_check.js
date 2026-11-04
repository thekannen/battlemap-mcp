// wscript.exe is a GUI executable. Godot must start it with blocking=false:
// blocking execute uses _wpopen/cmd.exe and would itself flash a console.
// Run(..., 0, true) hides PowerShell from creation and waits for its exit.
// The encoded script writes its result; no shell, redirection, or path is
// interpolated into PowerShell source here.
if (WScript.Arguments.length !== 1 ||
        !/^[A-Za-z0-9+/]+={0,2}$/.test(WScript.Arguments(0))) {
    WScript.Quit(1);
}
var shell = new ActiveXObject("WScript.Shell");
var powershell = shell.ExpandEnvironmentStrings("%SystemRoot%") +
    "\\System32\\WindowsPowerShell\\v1.0\\powershell.exe";
WScript.Quit(shell.Run('"' + powershell +
    '" -NoProfile -NonInteractive -EncodedCommand ' + WScript.Arguments(0), 0, true));
