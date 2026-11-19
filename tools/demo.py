"""Validate a fictional hypothesis and write a local, self-contained review."""
import argparse
import html
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from public_adam.offline import install
install()
from public_adam import Blocked, canonical, load_context, read_json, validate, LocalProposalSchema


def review_html(proposal, result, review):
    escape = html.escape
    fields = result.get('native_fields') or proposal.author_fields.model_dump()
    cards = ''.join('<article><h2>' + label + '</h2><p>' + escape(str(fields.get(key, ''))) + '</p></article>'
                    for key, label in [('initial_observation', 'Observation fictive'),
                                       ('alternative_hypothesis_h1', 'Hypothèse H1'),
                                       ('null_hypothesis_h0', 'Hypothèse H0'),
                                       ('entry_rules', 'Règle déclarée'), ('exit_rules', 'Sortie déclarée')])
    quotes = ''.join('<blockquote>' + escape(c.quote) + '</blockquote>' for c in proposal.citations)
    return '''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ADAM · Démonstration publique</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f1e9;color:#162b39;font:17px/1.6 system-ui,sans-serif}
header,main,footer{max-width:1080px;margin:auto;padding:28px}header{border-bottom:1px solid #bdc3c4}
.brand{font:52px Georgia,serif;margin:0}.kicker{color:#776128;font-size:13px;letter-spacing:.14em;text-transform:uppercase}
h1{font:36px Georgia,serif;margin:10px 0}h2{font-size:18px;margin:0 0 9px}p{margin:0 0 12px}
.notice,article{background:#fff;padding:22px;border:1px solid #d8d8cd;border-radius:8px;margin-bottom:18px}
.notice{border-left:5px solid #ac893b}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
blockquote{margin:0 0 18px;border-left:3px solid #ac893b;padding:16px;background:#fff}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 ui-monospace,monospace}
details{background:white;padding:20px;border:1px solid #d8d8cd;border-radius:8px}summary{cursor:pointer;font-weight:600}
footer{font-size:13px;color:#58666e}@media(max-width:700px){.grid{display:block}header,main,footer{padding:20px}.brand{font-size:42px}}
</style><header><p class="kicker">AURUM · Recherche expérimentale</p><p class="brand">ADAM</p>
<p>ARKS retrouve et vérifie les sources → ADAM aide à formuler des hypothèses → les backtests les mettent à l’épreuve.</p></header><main>
<p class="kicker">Démonstration sans modèle</p><h1>Une hypothèse, avant l’expérience</h1>
<div class="notice"><strong>Exemple entièrement fictif.</strong> Les valeurs et règles illustrent un contrat technique.
Aucun appel à un modèle, aucune requête ARKS en direct et aucun backtest. Une compilation valide ne prouve aucun effet.</div>
''' + '<div class="grid">' + cards + '</div><h2>Passage fictif contrôlé</h2>' + quotes + \
        '<article><h2>Résultat technique</h2><p>' + escape(result['status']) + '</p><p>Backtest autorisé : non. Validation scientifique : non effectuée.</p>' + \
        '<p>Empreinte de définition : <code>' + escape(str(result.get('definition_hash'))) + '</code></p></article>' + \
        '<details><summary>Revue complète et provenance</summary><pre>' + escape(review) + '</pre></details></main>' + \
        '<footer>Fichiers locaux · Aucun résultat de marché · Usage personnel, privé et non commercial gratuit ; exploitation commerciale sur accord écrit préalable.</footer></html>'


def main():
    parser = argparse.ArgumentParser(description='ADAM — validation publique hors ligne')
    parser.add_argument('--proposal', type=Path, default=ROOT / 'examples/proposal.json')
    parser.add_argument('--context', type=Path, default=ROOT / 'examples/host-context.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/public-demo')
    parser.add_argument('--schema', action='store_true', help='Afficher le schéma JSON de proposition')
    args = parser.parse_args()
    if args.schema:
        print(json.dumps(LocalProposalSchema().json_schema(), ensure_ascii=False, indent=2))
        return 0
    try:
        proposal, result, review = validate(read_json(args.proposal), load_context(args.context))
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'proposal-validated.json').write_text(json.dumps(proposal.model_dump(), ensure_ascii=False, indent=2), encoding='utf-8')
        (args.output / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        (args.output / 'review.txt').write_text(review, encoding='utf-8')
        (args.output / 'review.html').write_text(review_html(proposal, result, review), encoding='utf-8')
        print(json.dumps({'status': result['status'], 'model_calls': 0, 'backtests': 0,
                          'definition_hash': result['definition_hash'], 'review': str((args.output / 'review.html').resolve())}, ensure_ascii=True))
        return 0
    except (Blocked, ValueError, OSError) as error:
        print(json.dumps({'status': 'REFUSED', 'diagnostic': str(error)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
