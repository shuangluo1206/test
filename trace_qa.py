#!/usr/bin/env python3
"""短剧管线溯源核对工具
用法: python3 trace_qa.py <集号> [关键词]
例: python3 trace_qa.py 35 护家总对决
会沿 08←07←04b←run_config 链溯源,找病根在哪层
"""
import json, re, sys, glob
from pathlib import Path

RUN = Path("/Users/luoshuangshuang/Downloads/run_wedding_cat_full_opus48high_safev3_260722")
en = int(sys.argv[1]) if len(sys.argv)>1 else 35
kw = sys.argv[2] if len(sys.argv)>2 else ""

def load(p):
    try: return json.load(open(p, encoding="utf-8"))
    except: return None

print(f"\n{'='*70}")
print(f"溯源核对 EP{en}  关键词='{kw}'")
print(f"{'='*70}")

# === 1. 08 实际产出 ===
c = load(f"{RUN}/outputs/08_script_body_generation_ep{en:03d}.clean.json")
fs = c.get("final_script","") if c else ""
print(f"\n【08 EP{en} 实际产出】 字数={len(fs)}")
if kw and kw in fs:
    idx = fs.find(kw)
    print(f"  含'{kw}': ...{fs[max(0,idx-50):idx+80]}...")
elif kw:
    print(f"  ❌ 不含'{kw}'")

# === 2. 07 执行单(08该演什么) ===
print(f"\n【07 EP{en} 执行单】(08该演什么)")
p8 = open(f"{RUN}/prompts/08_script_body_generation_ep{en:03d}.prompt.md", encoding="utf-8").read()
m = re.search(r'### 本集去重执行单\s*\n(```json\s*)?(\{.*?\})\s*(```|\n###)', p8, re.S)
if m:
    plan = json.loads(m.group(2))
    print(f"  标题: {plan.get('标题')}")
    print(f"  事件ID: {plan.get('事件ID')}")
    print(f"  开场: {str(plan.get('开场情节',''))[:80]}")
    print(f"  收尾: {str(plan.get('收尾情节',''))[:80]}")
    print(f"  分场: {len(plan.get('分场计划',[]))}场")

# === 3. 07 原始block(07怎么排的) ===
print(f"\n【07 原始block】(07怎么排的EP{en})")
for bf in glob.glob(f"{RUN}/outputs/07_episode_planning.block_*.clean.json"):
    c7 = load(bf)
    if not c7: continue
    for e in c7.get("episode_outlines",[]):
        if e.get("episode_num")==en:
            print(f"  block: {bf.split('/')[-1]}")
            print(f"  phase: {e.get('phase')}")
            print(f"  state_change: {e.get('state_change','?')}")
            print(f"  payoff_level: {e.get('payoff_level','?')}")
            print(f"  conflict_mode: {e.get('conflict_mode','?')}")

# === 4. 04b 全季释放图(事件排哪集) ===
print(f"\n【04b 全季释放图】(事件排哪集)")
if kw:
    c4b = load(f"{RUN}/outputs/04b_dramatic_release_map.clean.json")
    blob = json.dumps(c4b, ensure_ascii=False) if c4b else ""
    for mm in re.finditer(rf'.{{0,80}}{re.escape(kw)}.{{0,150}}', blob):
        print(f"  ...{mm.group()[:250]}...")

# === 5. run_config 授权(高潮窗口/集数/配额) ===
print(f"\n【run_config 授权】(高潮窗口/约束)")
p8text = open(f"{RUN}/prompts/08_script_body_generation_ep{en:03d}.prompt.md", encoding="utf-8").read()
for key in ["major_climax_window","大高潮窗口","尾声最大集数","目标集数","最大动作对白单元数","maximum_chars","minimum_effective_chars"]:
    mm = re.search(rf'"{key}"\s*:\s*"?([^",\n}}]+)"?', p8text)
    if mm:
        print(f"  {key}: {mm.group(1)}")

# === 6. 管线自动校验 ===
print(f"\n【管线自动校验】")
cr = load(f"{RUN}/parsed/contract_reports/08_script_body_generation_ep{en:03d}.contract_report.json")
if cr:
    print(f"  contract状态: {cr.get('status') or cr.get('valid','?')}")
    for e in (cr.get("errors",[])+cr.get("warnings",[]))[:3]:
        if isinstance(e,dict):
            print(f"    - {e.get('code','')}: {str(e.get('message',''))[:80]}")

print(f"\n{'='*70}")
print("溯源链: 08产出 ← 07执行单 ← 04b事件排程 ← run_config授权")
print("判断: 若08符合07,07符合04b,但04b违反run_config → 病根在04b(上游污染)")
print(f"{'='*70}\n")
