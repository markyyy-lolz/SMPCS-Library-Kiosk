Option Explicit
Dim shell, fso, folder, interpreter, command, result
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
interpreter = folder & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(interpreter) Then
    command = Chr(34) & interpreter & Chr(34)
Else
    command = "pyw -3"
End If
command = command & " " & Chr(34) & folder & "\launch.pyw" & Chr(34) & " updates"
On Error Resume Next
result = shell.Run(command, 0, False)
If Err.Number <> 0 Then
    Err.Clear
    result = shell.Run("pythonw.exe " & Chr(34) & folder & "\launch.pyw" & Chr(34) & " updates", 0, False)
    If Err.Number <> 0 Then MsgBox "Install Python 3 for Windows, then run install.bat.", 16, "SMPCS Library"
End If
