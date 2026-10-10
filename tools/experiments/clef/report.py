"""讀 results.json 印彙整表（延遲中位 / 準確率 / 機率分佈 / token）。"""
import json, os, statistics as st
R = json.load(open(os.path.join(os.path.dirname(__file__), 'results.json'), encoding='utf-8'))
for model in ('clef-flash', 'clef'):
    for task in ('scene', 'track'):
        rs = [r for r in R if r['model'] == model and r['task'] == task]
        key = 'scene' if task == 'scene' else 'title'
        ok = [r for r in rs if r['out']['result']['answers'][key]['choice'] == r['truth']]
        lat = sorted(r['sec'] for r in rs)
        toks = [r['out']['result']['usage']['input_tokens'] for r in rs]
        print(model, task, f'n={len(rs)} acc={len(ok)}/{len(rs)} med={st.median(lat):.2f}s min={lat[0]:.2f} max={lat[-1]:.2f} avg_tok={st.mean(toks):.0f} total_tok={sum(toks)}')
        for r in rs:
            a = r['out']['result']['answers'][key]
            if a['choice'] != r['truth']:
                print('   錯:', r['name'], '正解', r['truth'], '→', a['choice'], round(a['probabilities'][a['choice']], 3), '正解機率', round(a['probabilities'][r['truth']], 3))
        pc = [r['out']['result']['answers'][key]['probabilities'][r['out']['result']['answers'][key]['choice']] for r in rs if r in ok]
        pw = [r['out']['result']['answers'][key]['probabilities'][r['out']['result']['answers'][key]['choice']] for r in rs if r not in ok]
        print('   對的 top 機率 min', round(min(pc), 3), '錯的 top 機率', [round(x, 3) for x in pw])
    for r in [r for r in R if r['model'] == model and r['task'] == 'scene']:
        a = r['out']['result']['answers']
        m = a['mark'].get('noul'); v = a['verify'].get('noul')
        if r['mark_truth'] is not None or v > 0.1:
            print('  ', r['name'], '問號正解', r['mark_truth'], 'p=', m, '| 驗證 p=', v)
    vs = [r['out']['result']['answers']['verify']['noul'] for r in R if r['model'] == model and r['task'] == 'scene']
    print('  verify p(有驗證窗) 全部 21 張(皆非驗證) max=', max(vs), 'mean=', round(sum(vs)/len(vs), 4))
    ws = [r['out']['result']['answers']['has_wood']['noul'] for r in R if r['model'] == model and r['task'] == 'track']
    print('  has_wood p (應皆低):', ws)
print(json.dumps(R[0]['out'], ensure_ascii=False)[:100])
