#include "engine_gen.h"
int main() {
  SFusionParams p; FE_DefaultParams(p); p.is_xau = true;
  CFusionEngine* e = new CFusionEngine(); e->Configure(p, "2024.12.26; 2025-01-02 ,2019/05/06", "2024.11.29");
  int fails = 0;
  auto chk = [&](const char* name, bool got, bool want) { printf("%-46s %s\n", name, got == want ? "OK" : "FAIL"); if(got != want) fails++; };
  chk("extra closed 2024-12-26", e->IsClosedDay(FE_MakeDate(2024, 12, 26)), true);
  chk("extra closed 2025-01-02", e->IsClosedDay(FE_MakeDate(2025, 1, 2)), true);
  chk("extra closed 2019-05-06 (slash format)", e->IsClosedDay(FE_MakeDate(2019, 5, 6)), true);
  chk("not closed 2024-12-27", e->IsClosedDay(FE_MakeDate(2024, 12, 27)), false);
  chk("extra early 2024-11-29", e->IsEarlyDay(FE_MakeDate(2024, 11, 29)), true);
  chk("XAU Good Friday 2013-03-29", e->IsClosedDay(FE_MakeDate(2013, 3, 29)), true);
  chk("XAU Good Friday 2016-03-25", e->IsClosedDay(FE_MakeDate(2016, 3, 25)), true);
  chk("XAU Good Friday 2019-04-19", e->IsClosedDay(FE_MakeDate(2019, 4, 19)), true);
  chk("XAU Thanksgiving Fri 2017-11-24", e->IsEarlyDay(FE_MakeDate(2017, 11, 24)), true);
  chk("XAU July4 2017-07-04", e->IsEarlyDay(FE_MakeDate(2017, 7, 4)), true);
  chk("XAU July4 observed 2020-07-03 (Sat→Fri)", e->IsEarlyDay(FE_MakeDate(2020, 7, 3)), true);
  chk("XAU July4 observed 2021-07-05 (Sun→Mon)", e->IsEarlyDay(FE_MakeDate(2021, 7, 5)), true);
  bool nn, fl, rl; int kd;
  e->TimeRulesAt(FE_MakeDate(2024, 12, 25) - 3600 * 4, nn, fl, rl, kd);   // 12/24 20:00 開始（早仕舞い日）
  chk("12/24 20:00 bar: early-day flat", fl && kd == 2, true);
  e->TimeRulesAt(FE_MakeDate(2024, 12, 25) + 3600 * 2, nn, fl, rl, kd);
  chk("12/25 02:00 bar: closed day", fl && nn && kd == 1, true);
  e->TimeRulesAt(FE_MakeDate(2024, 12, 23) + 3600 * 20, nn, fl, rl, kd);  // 12/23 は 12/24（平日）が休場でない→通常
  chk("12/23 20:00 bar: normal day", !fl && !nn && kd == 0, true);
  e->TimeRulesAt(FE_MakeDate(2024, 12, 26) - 3600 * 4 - 86400 * 0, nn, fl, rl, kd); // 12/25 20:00 開始 → 休場日（closed）
  chk("12/25 20:00 bar: closed", kd == 1, true);
  e->TimeRulesAt(FE_MakeDate(2024, 12, 27) - 3600 * 3, nn, fl, rl, kd);   // 12/26(追加休場) 21:00 → closed
  chk("12/26 21:00 bar (extra closed)", kd == 1 && fl, true);
  printf("%s\n", fails ? "CAL TEST FAILED" : "CAL TEST OK");
  return fails;
}
