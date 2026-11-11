"""Extract private photo GPS and compare it with optional local place references."""
import argparse
import math
from pathlib import Path

from media_library import catalog_dir, library_root
from photo_io import open_photo
from pipeline import album_media, load, save, stamp
from pipeline_paths import guard_output_tree


def distance(lat1, lon1, lat2, lon2):
    first, second = math.radians(lat1), math.radians(lat2)
    haversine = math.sin((second - first) / 2) ** 2
    haversine += math.cos(first) * math.cos(second) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    haversine = min(haversine, 1)
    return 6371000 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', help='Sibling album name in the shared trip folder')
    parser.add_argument('--places', type=Path, help='Local JSON list with name, lat, lon, radius_m and source')
    args = parser.parse_args()
    album = library_root(args.library)
    catalog = catalog_dir(args.library)
    guard_output_tree(catalog, writable=('photo_locations.json',))
    if args.places and args.places.resolve() == (catalog/'photo_locations.json').resolve():
        parser.error('Choose a separate place reference file.')
    places = load(args.places) if args.places else []
    rows = []
    for media in load(catalog/'media.json'):
        if not media['photo']:
            continue
        with open_photo(album_media(album, media['file'])) as image:
            exif = image.getexif()
            gps = exif.get_ifd(34853)
        if 2 not in gps or 4 not in gps:
            continue
        lat = sum(float(value) / divisor for value, divisor in zip(gps[2], (1, 60, 3600)))
        lon = sum(float(value) / divisor for value, divisor in zip(gps[4], (1, 60, 3600)))
        if gps.get(1) == 'S':
            lat = -lat
        if gps.get(3) == 'W':
            lon = -lon
        row = {'media_id': media['id'], 'file': media['file'], 'captured_local': str(exif.get(306, '')),
               'latitude': lat, 'longitude': lon, 'method': 'Embedded EXIF GPS'}
        if places:
            separation, nearest = min(((distance(lat, lon, p['lat'], p['lon']), p) for p in places),
                                      key=lambda pair: pair[0])
            if separation <= nearest['radius_m']:
                row.update(place=nearest['name'], distance_to_reference_m=round(separation, 1),
                           source=nearest['source'], method='Embedded EXIF GPS near a mapped public place')
        rows.append(row)
    save(catalog/'photo_locations.json', {'created': stamp(), 'gps_photos': len(rows), 'photos': rows})
    print(f'GPS extracted from {len(rows)} photos. Review any candidate place label in context.')


if __name__ == '__main__':
    main()
