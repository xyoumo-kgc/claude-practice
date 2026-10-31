// EA の流れ（初回読込＋仮想再生 → 新しい確定足ごとに Sync）を再現して、評価ログと取引一覧を書く
#include "engine_gen.h"
#include <fstream>
#include <map>

static bool parse_time(const char* s, datetime& out) {
  MqlDateTime d; memset(&d, 0, sizeof d);
  if(sscanf(s, "%d-%d-%d %d:%d:%d", &d.year, &d.mon, &d.day, &d.hour, &d.min, &d.sec) < 5) return false;
  out = StructToTime(d); return true;
}

static FILE* fe; static FILE* ft; static std::map<string,int> funnel; static int tradesLogged = 0;

static void drain(CFusionEngine* e) {
  for(int i = 0; i < e->m_nrows; i++) { fprintf(fe, "%s\n", FE_EvalCsv(e->m_rows[i]).c_str()); funnel[FE_CodeName(e->m_rows[i].code)]++; }
  e->m_nrows = 0;
  while(tradesLogged < e->m_ntrades) { fprintf(ft, "%s\n", FE_TradeCsv(e->m_trades[tradesLogged]).c_str()); tradesLogged++; }
  e->m_nev = 0;
}

int main(int argc, char** argv) {
  if(argc < 5) { fprintf(stderr, "usage: harness bars.csv SYMBOL init_bars out_prefix [fetch] [switches]\n"); return 2; }
  const char* path = argv[1]; string sym = argv[2]; int W = atoi(argv[3]); string out = argv[4];
  int fetch = argc > 5 ? atoi(argv[5]) : 300;
  string sw = argc > 6 ? argv[6] : "";
  int offset = argc > 7 ? atoi(argv[7]) : 0;
  std::ifstream in(path); string line; std::getline(in, line);
  MqlArray<MqlRates> all;
  while(std::getline(in, line)) {
    MqlRates r; memset(&r, 0, sizeof r);
    char ts[64]; double o, h, l, c, v;
    if(sscanf(line.c_str(), "%63[^,],%lf,%lf,%lf,%lf,%lf", ts, &o, &h, &l, &c, &v) < 5) continue;
    if(!parse_time(ts, r.time)) continue;
    r.time += (datetime)offset * 3600;
    r.open = o; r.high = h; r.low = l; r.close = c; all.v.push_back(r);
  }
  int N = ArraySize(all);
  SFusionParams p; FE_DefaultParams(p);
  string base = FE_SymbolBase(sym);
  p.s_nom = FE_NominalSpread(base); p.is_xau = (base == "XAUUSD"); p.server_offset_h = offset;
  if(sw.find("g3") != string::npos) p.g3 = true;
  if(sw.find("d1strict") != string::npos) p.d1_gate = 1;
  if(sw.find("d1soft") != string::npos) p.d1_gate = 2;
  if(sw.find("gap") != string::npos) p.gap_gate = true;
  if(sw.find("clear") != string::npos) p.clear_gate = true;
  if(sw.find("daily") != string::npos) p.cf_scope = 1;
  if(sw.find("support") != string::npos) p.support_gate = true;
  if(sw.find("slnode") != string::npos) p.sl_mode = 1;
  if(sw.find("p3") != string::npos) p.p3 = true;
  CFusionEngine* e = new CFusionEngine();
  e->Configure(p, "", "");
  if(W > N) W = N;
  MqlArray<MqlRates> init; init.v.assign(all.v.begin(), all.v.begin() + W);
  e->Load(init, W);
  fe = fopen((out + "_eval.csv").c_str(), "w"); ft = fopen((out + "_trades.csv").c_str(), "w");
  fprintf(fe, "%s\n", FE_EvalHeader().c_str()); fprintf(ft, "%s\n", FE_TradeHeader().c_str());
  e->m_phase = 0;
  if(e->m_first >= 0) for(int t = e->m_first; t < e->m_n; t++) { e->PreBarIndex(t); e->BarProcess(t); if(e->m_nrows > 4000) drain(e); }
  drain(e);
  if(W < N) { e->PreBarForming(all[W].time, all[W].open); drain(e); }
  e->m_phase = 1;
  // batch: 何本ごとに Sync するか（端末が止まっていた状況）。noforming: 形成中の足の始まりを見ない
  int batch = 1; bool forming = true;
  { size_t q = sw.find("batch="); if(q != string::npos) batch = atoi(sw.c_str() + q + 6); if(sw.find("noforming") != string::npos) forming = false; }
  for(int k = W; k < N; k += batch) {
    int kk = std::min(N - 1, k + batch - 1);
    int from = std::max(0, kk - fetch + 1);
    MqlArray<MqlRates> win; win.v.assign(all.v.begin() + from, all.v.begin() + kk + 1);
    int res = e->Sync(win, ArraySize(win));
    if(res != kk - k + 1) { fprintf(stderr, "Sync returned %d at k=%d\n", res, k); return 1; }
    drain(e);
    if(forming && kk + 1 < N) { e->PreBarForming(all[kk + 1].time, all[kk + 1].open); drain(e); }
  }
  e->CloseAtEnd(); drain(e);
  fclose(fe); fclose(ft);
  printf("bars=%d first=%d trades=%d\n", e->m_n, e->m_first, e->m_ntrades);
  for(auto& kv : funnel) printf("%s=%d ", kv.first.c_str(), kv.second);
  printf("\n");
  return 0;
}
