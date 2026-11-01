// CFusionEngine::Sync（毎時の取り直しと手元の照合）が、履歴の食い違いを見逃さないことを確かめる
//   SYNC_BARS=bars_EURUSD.csv ./synctest
#include "engine_gen.h"
#include <fstream>

static bool parse_time(const char* s, datetime& out) {
  MqlDateTime d; memset(&d, 0, sizeof d);
  if(sscanf(s, "%d-%d-%d %d:%d:%d", &d.year, &d.mon, &d.day, &d.hour, &d.min, &d.sec) < 5) return false;
  out = StructToTime(d); return true;
}

int main() {
  const char* bp = getenv("SYNC_BARS");
  std::ifstream in(bp ? bp : "bars_EURUSD.csv"); string line; std::getline(in, line);
  std::vector<MqlRates> all;
  while(std::getline(in, line) && all.size() < 3000) {
    MqlRates r; memset(&r, 0, sizeof r); char ts[64]; double o, h, l, c, v;
    if(sscanf(line.c_str(), "%63[^,],%lf,%lf,%lf,%lf,%lf", ts, &o, &h, &l, &c, &v) < 5) continue;
    if(!parse_time(ts, r.time)) continue;
    r.open = o; r.high = h; r.low = l; r.close = c; all.push_back(r);
  }
  if(all.size() < 2100) { printf("SYNC TEST: bars too short\n"); return 1; }
  SFusionParams p; FE_DefaultParams(p);
  CFusionEngine* e = new CFusionEngine();
  int fails = 0;
  auto fresh = [&]() { e->Configure(p, "", ""); MqlArray<MqlRates> a; a.v.assign(all.begin(), all.begin() + 2000); e->Load(a, 2000); e->m_phase = 1; };
  auto window = [&](int from, int to) { MqlArray<MqlRates> w; w.v.assign(all.begin() + from, all.begin() + to); return w; };
  auto check = [&](const char* name, int got, int want) {
    printf("%-44s got %2d want %2d %s\n", name, got, want, got == want ? "OK" : "FAIL"); if(got != want) fails++; };
  { fresh(); MqlArray<MqlRates> w = window(1700, 2001); check("1本追記", e->Sync(w, ArraySize(w)), 1); }
  { fresh(); MqlArray<MqlRates> w = window(1700, 2003); check("3本追記", e->Sync(w, ArraySize(w)), 3); }
  { fresh(); MqlArray<MqlRates> w = window(1700, 2000); check("新しい足なし", e->Sync(w, ArraySize(w)), 0); }
  { fresh(); MqlArray<MqlRates> w = window(0, 2001); check("手元の先頭より古い足を含む", e->Sync(w, ArraySize(w)), 1); }
  { fresh(); MqlArray<MqlRates> w = window(1700, 2001); w.v[150].close += 0.00001; check("重なり部分の終値が変わった", e->Sync(w, ArraySize(w)), -1); }
  { fresh(); MqlArray<MqlRates> w = window(1700, 2001); w.v.erase(w.v.begin() + 100); check("重なり部分の足が欠けた", e->Sync(w, ArraySize(w)), -1); }
  { fresh(); MqlArray<MqlRates> w = window(1700, 2001); MqlRates x = w.v[100]; x.time += 1800; w.v.insert(w.v.begin() + 101, x);
    check("重なり部分に足が挟まった", e->Sync(w, ArraySize(w)), -1); }
  { fresh(); MqlArray<MqlRates> w = window(1700, 2001); MqlRates x = w.v[199]; w.v.insert(w.v.begin() + 200, x);
    check("重なり部分に同じ時刻の足が重複", e->Sync(w, ArraySize(w)), -1); }
  { fresh(); MqlArray<MqlRates> w = window(1700, 1999); check("取得側が手元の最後の足より前で終わる", e->Sync(w, ArraySize(w)), -1); }
  { fresh(); MqlArray<MqlRates> w = window(2001, 2005); check("重なりがない（間が抜けている）", e->Sync(w, ArraySize(w)), -1); }
  { fresh(); MqlArray<MqlRates> w = window(1700, 2000); MqlRates s = w.v.back(); datetime t = s.time;
    do { t += 3600; } while(FE_DayOfWeek(t) != 6); s.time = t; w.v.push_back(s);
    check("末尾の土曜の足は捨てる", e->Sync(w, ArraySize(w)), 0); }
  printf("%s\n", fails ? "SYNC TEST FAILED" : "SYNC TEST OK");
  return fails ? 1 : 0;
}
