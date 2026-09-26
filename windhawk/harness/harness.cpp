// Runs winduo.wh.cpp outside Windhawk, for development.
//
// Supplies the handful of Windhawk API functions the mod uses, then calls the
// tool-mod callbacks directly. The mod file itself is included unchanged, so
// what compiles and runs here is exactly what gets submitted.
//
//   g++ -std=c++23 -O2 harness.cpp -o winduo-harness.exe <libs from @compilerOptions>
//   winduo-harness.exe [--preview] [--seconds N] [Setting=Value ...]

#include <windows.h>

#include <cstdarg>
#include <cstdio>
#include <map>
#include <string>

#define WH_MOD_ID L"winduo"

static std::map<std::wstring, int> g_intSettings = {
    {L"TriggerTravel", 10},  {L"FullEffectTravel", 75}, {L"ReleaseHysteresis", 4},
    {L"TiltLimit", 70},      {L"TopLean", 60},          {L"ViewingDistance", 30},
    {L"MaxBlurRadius", 90},  {L"MaxDim", 85},           {L"DimReach", 50},
    {L"HingeGlow", 50},      {L"Reflection", 50},       {L"LivePicture", 1},
    {L"DegreesPerPixel", 269}, {L"NeutralAngle", 100},  {L"CameraIndex", 0},
    {L"ConfidenceFloor", 35}, {L"Preview", 0},
};

int Wh_GetIntSetting(PCWSTR name, ...) {
    auto it = g_intSettings.find(name);
    return it == g_intSettings.end() ? 0 : it->second;
}

void Wh_Log(PCWSTR format, ...) {
    wchar_t buffer[1024];
    va_list args;
    va_start(args, format);
    _vsnwprintf_s(buffer, _countof(buffer), _TRUNCATE, format, args);
    va_end(args);
    SYSTEMTIME t;
    GetLocalTime(&t);
    fwprintf(stderr, L"%02d:%02d:%02d.%03d %ls\n", t.wHour, t.wMinute, t.wSecond,
             t.wMilliseconds, buffer);
    fflush(stderr);
}

BOOL Wh_SetFunctionHook(void*, void*, void**) { return TRUE; }

// With WINDUO_VISIBLE=1 the overlay reports that capture exclusion failed, so
// the mod holds one frame instead of a live picture and an ordinary screenshot
// can photograph the effect. Only this harness can do that; the mod always
// asks for exclusion.
static BOOL HarnessDisplayAffinity(HWND hwnd, DWORD affinity) {
    wchar_t value[8] = {};
    if (GetEnvironmentVariableW(L"WINDUO_VISIBLE", value, 8) && value[0] == L'1') {
        SetLastError(ERROR_NOT_SUPPORTED);
        return FALSE;
    }
    return SetWindowDisplayAffinity(hwnd, affinity);
}
#define SetWindowDisplayAffinity HarnessDisplayAffinity

#include "../winduo.wh.cpp"

int wmain(int argc, wchar_t** argv) {
    double seconds = 0;
    bool preview = false;
    for (int i = 1; i < argc; i++) {
        std::wstring arg = argv[i];
        if (arg == L"--preview") {
            preview = true;
        } else if (arg == L"--seconds" && i + 1 < argc) {
            seconds = _wtof(argv[++i]);
        } else if (auto eq = arg.find(L'='); eq != std::wstring::npos) {
            g_intSettings[arg.substr(0, eq)] = _wtoi(arg.c_str() + eq + 1);
        }
    }

    if (!WhTool_ModInit()) {
        return 1;
    }
    if (preview) {
        Sleep(1500);  // let the overlay and camera come up first
        g_intSettings[L"Preview"] = 1;
        WhTool_ModSettingsChanged();
    }
    if (seconds > 0) {
        Sleep(DWORD(seconds * 1000));
    } else {
        Wh_Log(L"running; press Enter to stop");
        getchar();
    }
    WhTool_ModUninit();
    Wh_Log(L"stopped cleanly");
    return 0;
}
