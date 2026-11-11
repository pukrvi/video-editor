"""Record chat notes or import the review player's JSON for the next edit."""
import argparse,json,hashlib
from pathlib import Path
from pipeline import ROOT,load,save,stamp,current_recipe
ap=argparse.ArgumentParser();ap.add_argument('--recipe',default=current_recipe());ap.add_argument('--import-file');ap.add_argument('--at',type=float,default=0);ap.add_argument('--kind',choices=['change','keep','private','music','framing'],default='change');ap.add_argument('--note');args=ap.parse_args()
recipe=load(ROOT/args.recipe)
if args.import_file:
    incoming=load(args.import_file)
    expected=hashlib.sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest()
    assert incoming.get('recipe_sha256')==expected,'Feedback belongs to a different recipe. Use that version with --recipe.'
    notes=incoming['notes']
else:
    assert args.note,'Supply --note or --import-file'
    notes=[{'at':args.at,'kind':args.kind,'text':args.note}]
existing=ROOT/'feedback/notes.json';log=load(existing) if existing.exists() else []
review_path=ROOT/recipe.get('public_review','config/public_review.json')
review=load(review_path)
fps=recipe['fps']
for n in notes:
    assert 0<=n['at']<=recipe['duration']
    s=next((s for s in recipe['shots'] if s['start_frame']/fps<=n['at']<(s['start_frame']+s['frames'])/fps),recipe['shots'][-1])
    record={**n,'recorded':stamp(),'version':recipe['version'],'perspective':recipe['perspective'],'shot':s['id'],'file':s['file'],'status':'pending'}
    if not any(all(old.get(k)==record.get(k) for k in ('at','kind','text','version','perspective')) for old in log):log.append(record)
    if n['kind']=='private':
        review['excluded_files']=sorted(set(review['excluded_files']+[s['file']]))
        for other in recipe['shots']:
            if other['file']==s['file']:review['approved_windows'].pop(other['id'],None)
save(existing,log);save(review_path,review)
print(f'{len(notes)} notes recorded. Apply them in a new version; private flags block re-use immediately.')
