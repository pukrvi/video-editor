"""Make a revision recipe without overwriting an existing export."""
import argparse,re
from pipeline import *
ap=argparse.ArgumentParser();ap.add_argument('--from-recipe',default=current_recipe());ap.add_argument('--version',required=True);ap.add_argument('--perspective');args=ap.parse_args()
assert re.fullmatch(r'(?:[a-z][a-z0-9_]*_)?v\d{2,}',args.version),'Use a version such as v04 or krabi_v02'
r=load(ROOT/args.from_recipe);r['version']=args.version;r['finalcut_export']=False
if args.perspective:r['perspective']=args.perspective;r['project_slug']=r.get('destination','Phuket')+'_'+re.sub(r'[^A-Za-z0-9_-]','_',args.perspective)
out=ROOT/'config'/(f"{r['version']}.json" if '_' in r['version'] else f"{r['perspective'].lower()}_{r['version']}.json")
assert not out.exists() and not (ROOT/'exports'/r['version']).exists(),'This version already exists; choose a new version number.'
if r.get('media_library'):
    review=load(ROOT/r['public_review'])
    review.update(version=r['version'],inherited_from=r['public_review'])
    r['public_review']=f"config/public_review_{r['version']}.json"
    assert not (ROOT/r['public_review']).exists(),'This version already has a review file.'
    save(ROOT/r['public_review'],review)
save(out,r);print(out)
