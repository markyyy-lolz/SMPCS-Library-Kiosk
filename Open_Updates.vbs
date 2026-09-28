Option Explicit
Dim shell, fso, folder, exe
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
exe = folder & "\SMPCS_Library.exe"
If Not fso.FileExists(exe) Then
    MsgBox "Place Open_Updates.vbs beside SMPCS_Library.exe, then open it again.", 48, "SMPCS Library Updates"
Else
    shell.CurrentDirectory = folder
    shell.Run Chr(34) & exe & Chr(34) & " updates", 0, False
End If
