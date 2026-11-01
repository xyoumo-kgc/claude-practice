// MQL5 の組み込み関数の C++ 代用（判定エンジンの照合専用）
#pragma once
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <cfloat>
#include <climits>
#include <ctime>
#include <string>
#include <vector>
#include <sstream>
#include <iostream>
#include <algorithm>

typedef long long datetime;
typedef unsigned char uchar;
typedef unsigned short ushort;
typedef unsigned int uint;
// ulong は sys/types.h の unsigned long（64bit）を使う
typedef int color;
using string = std::string;

#define EMPTY_VALUE DBL_MAX
#define TIME_DATE 1
#define TIME_MINUTES 2
#define TIME_SECONDS 4

struct MqlDateTime { int year, mon, day, hour, min, sec, day_of_week, day_of_year; };
struct MqlRates { datetime time; double open, high, low, close; long long tick_volume; int spread; long long real_volume; };

template<class T> struct MqlArray {
  std::vector<T> v;
  T& operator[](int i) {
    if(i < 0 || i >= (int)v.size()) { fprintf(stderr, "array out of range: %d / %zu\n", i, v.size()); abort(); }
    return v[i];
  }
  const T& operator[](int i) const {
    if(i < 0 || i >= (int)v.size()) { fprintf(stderr, "array out of range (const): %d / %zu\n", i, v.size()); abort(); }
    return v[i];
  }
};
template<class T> int ArrayResize(MqlArray<T>& a, int n, int reserve = 0) { (void)reserve; if(n < 0) return -1; a.v.resize(n); return n; }
template<class T> int ArraySize(const MqlArray<T>& a) { return (int)a.v.size(); }
template<class T> void ArrayFree(MqlArray<T>& a) { a.v.clear(); }

inline double MathMax(double a, double b) { return a > b ? a : b; }
inline double MathMin(double a, double b) { return a < b ? a : b; }
inline double MathAbs(double a) { return std::fabs(a); }
inline double MathFloor(double a) { return std::floor(a); }
inline double MathSqrt(double a) { return std::sqrt(a); }

inline bool TimeToStruct(datetime t, MqlDateTime& s) {
  time_t tt = (time_t)t; struct tm g; gmtime_r(&tt, &g);
  s.year = g.tm_year + 1900; s.mon = g.tm_mon + 1; s.day = g.tm_mday; s.hour = g.tm_hour; s.min = g.tm_min; s.sec = g.tm_sec;
  s.day_of_week = g.tm_wday; s.day_of_year = g.tm_yday; return true;
}
inline datetime StructToTime(MqlDateTime& s) {
  struct tm g; memset(&g, 0, sizeof g);
  g.tm_year = s.year - 1900; g.tm_mon = s.mon - 1; g.tm_mday = s.day; g.tm_hour = s.hour; g.tm_min = s.min; g.tm_sec = s.sec;
  return (datetime)timegm(&g);
}
inline string TimeToString(datetime t, int flags = TIME_DATE | TIME_MINUTES) {
  MqlDateTime s; TimeToStruct(t, s); char b[64];
  if((flags & TIME_DATE) && (flags & TIME_SECONDS)) snprintf(b, sizeof b, "%04d.%02d.%02d %02d:%02d:%02d", s.year, s.mon, s.day, s.hour, s.min, s.sec);
  else if((flags & TIME_DATE) && (flags & TIME_MINUTES)) snprintf(b, sizeof b, "%04d.%02d.%02d %02d:%02d", s.year, s.mon, s.day, s.hour, s.min);
  else if(flags & TIME_DATE) snprintf(b, sizeof b, "%04d.%02d.%02d", s.year, s.mon, s.day);
  else snprintf(b, sizeof b, "%02d:%02d", s.hour, s.min);
  return b;
}
inline datetime StringToTime(const string& s) {
  MqlDateTime d; memset(&d, 0, sizeof d);
  if(sscanf(s.c_str(), "%d.%d.%d %d:%d", &d.year, &d.mon, &d.day, &d.hour, &d.min) < 3) return 0;
  return StructToTime(d);
}
inline string DoubleToString(double v, int digits = 8) { char b[128]; snprintf(b, sizeof b, "%.*f", digits, v); return b; }
inline string IntegerToString(long long v, int len = 0, ushort fill = ' ') {
  string s = std::to_string(v); while((int)s.size() < len) s = string(1, (char)fill) + s; return s; }
inline int StringLen(const string& s) { return (int)s.size(); }
inline string StringSubstr(const string& s, int start, int len = -1) {
  if(start < 0 || start >= (int)s.size()) return ""; if(len < 0) return s.substr(start); return s.substr(start, len); }
inline int StringFind(const string& s, const string& f, int start = 0) { size_t p = s.find(f, start); return p == string::npos ? -1 : (int)p; }
inline int StringReplace(string& s, const string& f, const string& r) {
  if(f.empty()) return 0; int n = 0; size_t p = 0;
  while((p = s.find(f, p)) != string::npos) { s.replace(p, f.size(), r); p += r.size(); n++; } return n; }
inline ushort StringGetCharacter(const string& s, int pos) { return (ushort)(unsigned char)s[pos]; }
inline int StringSplit(const string& s, ushort sep, MqlArray<string>& out) {
  out.v.clear(); string cur; for(char ch : s) { if((ushort)(unsigned char)ch == sep) { out.v.push_back(cur); cur.clear(); } else cur += ch; }
  out.v.push_back(cur); if(s.empty()) out.v.clear(); return (int)out.v.size(); }
inline int StringTrimLeft(string& s) { size_t p = s.find_first_not_of(" \t\r\n"); int n = (int)(p == string::npos ? s.size() : p); s.erase(0, n); return n; }
inline int StringTrimRight(string& s) { size_t p = s.find_last_not_of(" \t\r\n"); int n = (int)(p == string::npos ? s.size() : s.size() - p - 1); s.erase(s.size() - n); return n; }
inline bool StringToUpper(string& s) { for(auto& ch : s) ch = (char)toupper((unsigned char)ch); return true; }
inline long long StringToInteger(const string& s) { return atoll(s.c_str()); }

template<class T> T fmt_arg(T v) { return v; }
inline const char* fmt_arg(const std::string& s) { return s.c_str(); }
template<class... A> string StringFormat(const string& f, A... a) {
  string ff = f; StringReplace(ff, "I64", "ll"); char buf[8192]; snprintf(buf, sizeof buf, ff.c_str(), fmt_arg(a)...); return buf; }
