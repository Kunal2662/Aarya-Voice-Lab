; AARYA Voice Lab -- Windows installer.
;
; Orchestrates the EXISTING, already-tested provisioning architecture
; (scripts/install_env.ps1, the aarya-voice CLI, pipeline.hf_auth,
; pipeline.indicf5_provisioning) -- it does not reimplement any of their
; logic. This is an ONLINE installer: it downloads PyTorch/CUDA wheels
; (~2-3 GB) and the IndicF5 model (~1.4 GB) from PyPI/PyTorch's wheel
; index and HuggingFace during setup. It does not work without internet
; access, and does not pretend to.
;
; Build: see docs/INDICF5_INSTALLER.md's "Windows installer artifact"
; section for the full, exact, reproducible build command.
;
; UNSIGNED DEVELOPMENT BUILD. Not code-signed -- see
; docs/INDICF5_INSTALLER.md's installer security review for what that
; means and what would be required before a production-signed release.

#include "AaryaVoiceLabDefines.iss"

[Setup]
AppId={{B4E6C9E1-5A3D-4F2B-9C8E-7D1A2F3B4C5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install under %LocalAppData% -- fully user-writable, no UAC
; prompt, no privilege escalation. This is a personal ML tool, not a
; system service; there is no legitimate reason for it to need admin.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=..\installer\dist
OutputBaseFilename=AaryaVoiceLab-Setup
Compression=lzma2
SolidCompression=yes
SetupLogging=yes
WizardStyle=modern
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Runtime source -- excludes .git, .envs, caches, generated data/audio,
; and the test suite (dev-only, not needed at runtime). See docs/
; INDICF5_INSTALLER.md's file-inclusion rationale.
Source: "..\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc"
Source: "..\requirements\*"; DestDir: "{app}\requirements"; Flags: ignoreversion recursesubdirs
Source: "..\configs\*"; DestDir: "{app}\configs"; Flags: ignoreversion recursesubdirs
Source: "..\schemas\*"; DestDir: "{app}\schemas"; Flags: ignoreversion recursesubdirs
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs
Source: "..\manifests\*"; DestDir: "{app}\manifests"; Flags: ignoreversion recursesubdirs
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Code]
var
  TokenPage: TInputQueryWizardPage;
  GpuAccel: String;
  SetupSucceeded: Boolean;
  SmokeTestPassed: Boolean;

// Sets/clears an environment variable on THIS (the installer's own)
// process -- inherited by exactly one child process it Exec()s
// afterward (login), then cleared immediately. This is how the
// HuggingFace token reaches _installer_steps.py without ever touching
// the command line (which can appear in process listings) or any log
// file this installer writes.
function SetEnvironmentVariableW(lpName, lpValue: String): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

// A bare MsgBox() blocks forever under /VERYSILENT: /SUPPRESSMSGBOXES only
// suppresses Inno Setup's OWN built-in dialogs, never a script's own
// MsgBox() calls -- confirmed live during Phase 8 real-machine validation
// (a silent test run hung indefinitely on this exact call, requiring a
// manual taskkill to unblock). A genuinely silent/unattended install must
// never wait on a human; every status this installer would otherwise show
// in a box still goes to the setup log either way.
function SafeMsgBox(const Msg: String; MsgType: TMsgBoxType; Buttons: Cardinal): Integer;
begin
  if WizardSilent() then
  begin
    Log('SILENT (MsgBox suppressed): ' + Msg);
    Result := IDOK;
  end
  else
    Result := MsgBox(Msg, MsgType, Buttons);
end;

// Second bug found in the same real-machine pass: WizardSilent() is
// install-wizard-only -- calling it from CurUninstallStepChanged raised
// "Internal error: Cannot call 'WizardSilent' function during Uninstall",
// a FATAL exception that aborted the entire uninstall before any file
// was removed (confirmed live: nothing in [UninstallDelete], and none of
// the [Files]-tracked application files, were actually deleted).
// UninstallSilent() is the uninstall-context equivalent.
function SafeMsgBoxUninstall(const Msg: String; MsgType: TMsgBoxType; Buttons: Cardinal): Integer;
begin
  if UninstallSilent() then
  begin
    Log('SILENT (MsgBox suppressed): ' + Msg);
    Result := IDOK;
  end
  else
    Result := MsgBox(Msg, MsgType, Buttons);
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  Found: Boolean;
begin
  Found := Exec('py.exe', '-3.12 --version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if not Found then
    Found := Exec('python.exe', '--version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  Result := Found;
  if not Result then
    SafeMsgBox('Python 3.12 was not found on this system.' + #13#10 + #13#10 +
      'AARYA Voice Lab requires Python 3.12. Install it from https://www.python.org/downloads/ ' +
      '(check "Add python.exe to PATH" during its install), then run this setup again.',
      mbCriticalError, MB_OK);
end;

procedure InitializeWizard();
begin
  TokenPage := CreateInputQueryPage(wpSelectDir,
    'HuggingFace Authentication',
    'IndicF5''s model is gated and requires an approved HuggingFace account.',
    'AI4Bharat''s IndicF5 checkpoint is gated on HuggingFace: downloading it requires an account with ' +
    'access to ai4bharat/IndicF5 approved, and an access token. If you don''t have this yet, visit ' +
    'https://huggingface.co/ai4bharat/IndicF5 to request access, then create a token at ' +
    'https://huggingface.co/settings/tokens.' + #13#10 + #13#10 +
    'You may leave this blank and authenticate later by running "aarya-voice hf-login" from an ' +
    'installed shortcut -- setup will still complete, but the model download and voice-generation ' +
    'test will be skipped until you do.');
  TokenPage.Add('HuggingFace access token (input hidden):', True);
end;

procedure UpdateStatus(const Msg: String);
begin
  WizardForm.StatusLabel.Caption := Msg;
  WizardForm.FilenameLabel.Caption := Msg;
  WizardForm.Refresh;
  Log('STATUS: ' + Msg);
end;

function RunLoggedStepEx(const Description, Exe, Params: String; var ResultCode: Integer): Boolean;
begin
  UpdateStatus(Description);
  Result := Exec(Exe, Params, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log(Description + ': exit code ' + IntToStr(ResultCode));
end;

function RunLoggedStep(const Description, Exe, Params: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := RunLoggedStepEx(Description, Exe, Params, ResultCode) and (ResultCode = 0);
end;

function DetectGpuAccel(): String;
var
  ResultCode: Integer;
  Launched: Boolean;
  NvidiaSmiPath: String;
begin
  UpdateStatus('DETECTING GPU');
  // Presence-only: which accelerator wheel index to install from. The
  // real, authoritative capability check (VRAM tier, CUDA runtime, an
  // actual model load) happens later via `indicf5-report` -- this never
  // by itself claims "GPU execution available".
  //
  // Bug found during Phase 8 real-machine validation, in two stages:
  // (1) Exec() with a bare 'nvidia-smi.exe' failed to launch at all --
  // Exec() does not reliably search PATH/System32 for an unqualified
  // filename. (2) Switching to '{sys}\nvidia-smi.exe' STILL failed:
  // Setup.exe itself is a 32-bit process, so '{sys}' (System32) is
  // WOW64-redirected to SysWOW64 -- where the 64-bit-only nvidia-smi.exe
  // does not exist. '{sysnative}' is Inno Setup's documented escape from
  // that redirection, specifically for a 32-bit installer reaching a
  // 64-bit system tool.
  NvidiaSmiPath := ExpandConstant('{sysnative}\nvidia-smi.exe');
  Launched := Exec(NvidiaSmiPath, '--query-gpu=name --format=csv,noheader', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if Launched then
    Log('nvidia-smi launched=True exit=' + IntToStr(ResultCode) + ' path=' + NvidiaSmiPath)
  else
    Log('nvidia-smi launched=False path=' + NvidiaSmiPath);
  if Launched and (ResultCode = 0) then
  begin
    Log('nvidia-smi found -- installing CUDA wheels');
    Result := 'cuda';
  end
  else
  begin
    Log('nvidia-smi not found or failed -- installing CPU-only wheels');
    Result := 'cpu';
  end;
end;

procedure EnsureDataDirectories();
var
  Dirs: TArrayOfString;
  I: Integer;
begin
  // The exact directories configs/release.yaml's data_directories names
  // -- the "creating one is a separate, explicit first-run step" this
  // project's own release groundwork (docs/WINDOWS_RELEASE.md) deferred.
  // This installer is that step.
  Dirs := ['source', 'datasets', 'public_datasets', 'models', 'experiments',
           'benchmarks', 'reports', 'logs', 'manifests', 'data'];
  for I := 0 to GetArrayLength(Dirs) - 1 do
    ForceDirectories(ExpandConstant('{app}\') + Dirs[I]);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvTtsPython: String;
  Token: String;
  LoginResult: Boolean;
  LoginExitCode: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;

  SetupSucceeded := True;
  SmokeTestPassed := False;
  EnsureDataDirectories();

  EnvTtsPython := ExpandConstant('{app}\.envs\env-tts\Scripts\python.exe');

  if FileExists(EnvTtsPython) then
  begin
    Log('env-tts already exists -- reusing it (matches install_env.ps1''s own refuse-to-overwrite behavior)');
  end
  else
  begin
    GpuAccel := DetectGpuAccel();
    if not RunLoggedStep('INSTALLING RUNTIME',
         'powershell.exe',
         '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\scripts\install_env.ps1') +
         '" -EnvName env-tts -Accel ' + GpuAccel) then
    begin
      SetupSucceeded := False;
      SafeMsgBox('Setting up the AARYA Voice Lab runtime environment failed.' + #13#10 + #13#10 +
        'Your files were installed, but the Python environment and model runtime were not. See the ' +
        'setup log (Setup Log*.txt next to this installer, or via /LOG) for details, then try running ' +
        '"scripts\install_env.ps1 -EnvName env-tts" from an installed shortcut manually.',
        mbError, MB_OK);
      Exit;
    end;
  end;

  // Silent/unattended installs (a named Phase-1 evaluation criterion)
  // read the token from the AARYA_INSTALLER_HFTOKEN environment variable
  // on the launching process, NOT a /HFTOKEN=... command-line parameter.
  //
  // SECURITY INCIDENT found and fixed during Phase 8 real-machine
  // validation: an earlier version of this script accepted the token as
  // a /HFTOKEN=... command-line parameter. Inno Setup itself -- before
  // any of this script's own code runs -- unconditionally records its
  // own full command line (every /PARAM=value, verbatim) into the
  // /LOG setup log as a "Setup command line:" entry. A real token was
  // captured this way during testing, written in plaintext to a log
  // file; discovered, and the affected log files were deleted
  // immediately (see docs/INDICF5_INSTALLER.md's installer security
  // review for the full record). An environment variable is never part
  // of a process's command line and is not subject to this logging.
  Token := ExpandConstant('{%AARYA_INSTALLER_HFTOKEN|}');
  if Token = '' then
    Token := TokenPage.Values[0];

  UpdateStatus('AUTHENTICATING HUGGING FACE');
  SetEnvironmentVariableW('AARYA_INSTALLER_HF_TOKEN', Token);
  LoginResult := RunLoggedStepEx('AUTHENTICATING HUGGING FACE', EnvTtsPython,
    ExpandConstant('"{app}\scripts\_installer_steps.py" login'), LoginExitCode);
  SetEnvironmentVariableW('AARYA_INSTALLER_HF_TOKEN', '');
  Token := '';

  if LoginExitCode = 2 then
  begin
    Log('No HuggingFace token provided and no existing login found -- skipping provisioning and the smoke test.');
    Exit;
  end;
  if (not LoginResult) or (LoginExitCode <> 0) then
  begin
    SafeMsgBox('HuggingFace authentication failed.' + #13#10 + #13#10 +
      'This can mean the token was genuinely rejected, or that a transient network problem reaching ' +
      'huggingface.co occurred (see the setup log for which). IndicF5 access requires an approved ' +
      'HuggingFace account -- sign in, accept the model access agreement at ' +
      'https://huggingface.co/ai4bharat/IndicF5, and run "aarya-voice hf-login" from an installed ' +
      'shortcut to retry.',
      mbError, MB_OK);
    Exit;
  end;

  if not RunLoggedStep('DOWNLOADING MODEL', EnvTtsPython, ExpandConstant('"{app}\scripts\_installer_steps.py" provision')) then
  begin
    SafeMsgBox('Downloading or verifying the IndicF5 model failed.' + #13#10 + #13#10 +
      'This can happen from a network interruption, a corrupted partial download, or the ' +
      'HuggingFace account not yet having access to ai4bharat/IndicF5 approved. See the setup log ' +
      'for the specific reason, then re-run "aarya-voice indicf5-report" from an installed shortcut ' +
      'to retry -- already-downloaded files are reused, not re-fetched.',
      mbError, MB_OK);
    Exit;
  end;

  SmokeTestPassed := RunLoggedStep('TESTING VOICE RUNTIME', EnvTtsPython,
    '-m aarya_voice_lab.cli.main indicf5-report');
  if not SmokeTestPassed then
    SafeMsgBox('The real voice-generation test did not pass.' + #13#10 + #13#10 +
      'Setup, authentication, and model download all completed, but generating real speech on this ' +
      'GPU did not succeed -- most often insufficient VRAM or an unsupported GPU. See the setup log, ' +
      'or run "aarya-voice indicf5-report" from an installed shortcut for the full diagnostic report.',
      mbError, MB_OK)
  else
    SafeMsgBox('READY.' + #13#10 + #13#10 +
      'AARYA Voice Lab generated and validated real speech on this machine. Use the ' +
      '"AARYA Voice Lab (Command Prompt)" shortcut to run it.',
      mbInformation, MB_OK);
end;

// Uninstall must never delete real user data (recordings, embeddings,
// trained models, imported source audio) without a SEPARATE, explicit
// confirmation beyond "uninstall this program" -- mirrors
// aarya_voice_lab.release.is_safe_to_delete_without_confirmation() and
// configs/release.yaml's uninstall_protected_directories exactly.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ProtectedDirs: TArrayOfString;
  I: Integer;
  AnyProtectedDirExists: Boolean;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  ProtectedDirs := ['source', 'data', 'models', 'public_datasets'];
  AnyProtectedDirExists := False;
  for I := 0 to GetArrayLength(ProtectedDirs) - 1 do
    if DirExists(ExpandConstant('{app}\') + ProtectedDirs[I]) then
      AnyProtectedDirExists := True;
  if AnyProtectedDirExists then
    // Acknowledged. Nothing to do beyond informing -- [UninstallDelete]
    // below already excludes these directories; this box exists purely
    // to inform, not to gate (SafeMsgBox's return value is unused).
    SafeMsgBoxUninstall('AARYA Voice Lab will be uninstalled. The following directories may contain real ' +
      'recordings, biometric embeddings, or trained models and will be LEFT IN PLACE at ' +
      ExpandConstant('{app}') + ': source, data, models, public_datasets.' + #13#10 + #13#10 +
      'Delete them yourself only if you are certain -- this uninstaller will not remove them.',
      mbInformation, MB_OK);
end;

[UninstallDelete]
; The .envs Python environments are installer-managed, not user data --
; safe to remove without special confirmation, same as scripts/
; install_env.sh's own env deletion story ("remove it deliberately").
Type: filesandordirs; Name: "{app}\.envs"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\reports"
Type: filesandordirs; Name: "{app}\benchmarks"
Type: filesandordirs; Name: "{app}\experiments"
; source/data/models/public_datasets deliberately NOT listed here -- see
; CurUninstallStepChanged above and docs/WINDOWS_RELEASE.md.

[Icons]
Name: "{group}\AARYA Voice Lab (Command Prompt)"; Filename: "{cmd}"; Parameters: "/K echo AARYA Voice Lab -- try: .envs\env-tts\Scripts\python.exe -m aarya_voice_lab.cli.main indicf5-report"; WorkingDir: "{app}"
Name: "{group}\Uninstall AARYA Voice Lab"; Filename: "{uninstallexe}"

[Run]
Filename: "{cmd}"; Parameters: "/K echo AARYA Voice Lab -- try: .envs\env-tts\Scripts\python.exe -m aarya_voice_lab.cli.main indicf5-report"; WorkingDir: "{app}"; Description: "Open a command prompt in the install folder"; Flags: postinstall skipifsilent unchecked
