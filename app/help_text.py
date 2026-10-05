"""Every setting's name and its explanation, in one place.

The window, the profile editor and the tests all read this, so a label and its help cannot drift apart, and a
setting cannot be added without saying what it does (tests/app/test_help.py).

Each entry is ``key: (label, help)``. Keys named after a ``Settings`` or ``KeepProfile`` field belong to that field.
Help is plain text; a blank line starts a new paragraph.
"""
from dataclasses import fields

from app.settings import KeepProfile, Settings

REPROCESS_NOTE = "Changing this goes through your finished videos again the next time you process."

HELP = {
    # --- folders and the run ---------------------------------------------------------------------------------------
    'input_folder': ('Videos to process',
                     'The folder with your jump videos. Folders inside it are included.\n\n'
                     'Nothing in this folder is ever changed, renamed or deleted.'),
    'output_folder': ('Save clips to',
                      'Where the clips go. It must not be inside the videos folder, and the videos folder must not '
                      'be inside it.\n\nThe app also keeps its own record of what it has finished in here, so the '
                      'same folder next time means nothing is done twice.'),
    'keep_watching': ('Keep watching for new videos',
                      'After the videos already in the folder, carry on processing new ones as they finish copying '
                      'in, until you press Stop.\n\nLeave it off to stop when the folder is done.'),
    'profiles': ('What to keep',
                 'Each line is one kind of clip, for example "exit and freefall with someone in view". A video can '
                 'produce clips for several of them.\n\nDouble-click a line to change it. Untick it to keep it for '
                 'later without cutting anything for it.'),
    'presets': ('Add a ready-made profile',
                'Starting points such as Whole skydive, Exit only, Landing and Group freefall. The editor opens so '
                'you can adjust it before it is added.'),

    # --- a keep profile --------------------------------------------------------------------------------------------
    'name': ('Profile name', 'Used in the clip folder and file names, so keep it short. No semicolons.'),
    'enabled': ('Use this profile', 'Off keeps the profile in the list but cuts nothing for it.'),
    'phases': ('Parts of the jump to keep',
               'A moment is kept only if it falls in one of the ticked parts. Hover over a part to see what it '
               'means.\n\nThe end of freefall is the hardest part to pin down, so a second or two of extra footage '
               'after (below) is worth having.'),
    'min_person_count': ('People in view, at least',
                         'How many people must be visible at that moment.\n\n'
                         'This counts anyone the camera can see, INCLUDING YOU. Under canopy or on landing your own '
                         'legs, arms or hands are often in the picture, and they count as one person. So "1" does '
                         'not mean "someone else is there".\n\n'
                         'Set 0 to keep moments with nobody in view.'),
    'min_total_area_percent': ('People fill at least (% of the picture)',
                               'A box is drawn round each person found, and the boxes are added up.\n\n'
                               '20% is roughly one person close to the camera. Jumpers across the formation or far '
                               'away may be only 1 to 3%. Set this too high and distant footage produces no clips '
                               'at all.\n\nBoxes that overlap are both counted, so a tight group can go over 100%. '
                               'Set 0 for no requirement.'),
    'margin_before_seconds': ('Start each clip earlier by (seconds)',
                              'Extra footage added before the first matching moment, so the clip does not start '
                              'abruptly. It never goes back past the start of the video.'),
    'margin_after_seconds': ('End each clip later by (seconds)',
                             'Extra footage added after the last matching moment.\n\n'
                             'In testing, 2 seconds kept the whole freefall on 85% of jumps against 71% with 1 '
                             'second, because break-off is hard to place exactly.'),
    'min_span_seconds': ('Ignore matches shorter than (seconds)',
                         'A matching stretch shorter than this is dropped, so a one-second flicker does not become '
                         'a clip.\n\nIt is measured before the extra footage is added: 4 here with 2 seconds extra '
                         'each side gives clips of at least 8 seconds. Set 0 to keep every match.'),
    'max_gap_seconds': ('Join matches separated by up to (seconds)',
                        'If the match drops out briefly, for example someone leaves the picture for a moment, the '
                        'gap is filled in so you get one clip instead of two.\n\n'
                        'Only gaps with a match on both sides are filled. Set 0 to never join.'),

    'people_gap_seconds': ('Join gaps while people are still in view, up to (seconds)',
                           'For footage where the camera drifts off the group. A gap between two matches is filled, '
                           'however little of the picture people fill, as long as enough people are still in view '
                           '(the number below).\n\n'
                           'A moment inside the gap without them, such as the camera looking away, is let through '
                           'if it is no longer than "Join matches separated by" above. So set that to the longest '
                           'look-away you will accept, and this to the longest drift.\n\n'
                           'The gap needs a match on both sides, so this never makes a clip longer at its ends. '
                           'Set 0 to switch it off.'),
    'people_gap_count': ('People still in view means at least',
                         'How many people must be found for a moment to count as "still in view" for the join '
                         'above. It is only about the count: how much of the picture they fill does not matter '
                         'here.\n\nLike every count, it includes you if you are in your own picture.'),

    'folder': ('Folder for this profile\'s clips',
               'Used when clips are organised as "A folder per profile". Leave it empty for a folder named after '
               'the profile, inside your clips folder.\n\n'
               'Type a name to use a different folder inside the clips folder; two profiles can share one. Or type '
               'a full path, such as D:\\Day tape, to put this profile\'s clips somewhere else entirely.'),

    # --- basic mode: the three built-in choices --------------------------------------------------------------------
    'basic_trim': ('Trim my footage',
                   'Cuts each video down to the jump itself and throws nothing else away: your originals are never '
                   'touched.\n\n'
                   'Keeps exit, freefall, break-off and the opening, starting a couple of seconds before exit and '
                   'ending when the canopy is open. It does not look for people, so it is the fastest choice.\n\n'
                   'Tick the landing to get a second clip of the final approach and touchdown, with a few seconds '
                   'either side.\n\nClips go into a "Trimmed" folder, named after each video.'),
    'basic_a': ('A grade (day tape)',
                'The good stuff: moments with at least 1 person in view filling at least 20% of the picture, from '
                'exit to the end of break-off. Short drop-outs of up to 2 seconds are joined.\n\n'
                'Tick canopy to also keep canopy flight with at least 2 people filling 20%. That count includes '
                'you: your own legs or arms in the picture are one of the two.\n\n'
                'Clips go into an "A grade" folder, named after each video.'),
    'basic_b': ('B grade',
                'Everything A grade keeps, plus footage a wandering camera would lose: people need fill only 10% '
                'of the picture, gaps of up to 6 seconds are joined, and gaps of up to 10 seconds are joined '
                'while at least 3 people are still in view.\n\n'
                'Clips go into a "B grade" folder, named after each video. Because B includes A, the same '
                'freefall will be in both folders when both are ticked.'),

    # --- advanced: output ------------------------------------------------------------------------------------------
    'cut_enabled': ('What to produce',
                    'Clips and timelines, or timelines only.\n\n'
                    'A timeline is a spreadsheet (CSV) with one row for each moment of the video: which part of '
                    'the jump it is, how many people are in view, and which profiles it matched. With timelines '
                    'only, no clips are made or changed.\n\n'
                    'Clips start at the nearest keyframe of the original, so they can run a second or two long.'),
    'output_layout': ('Organise clips',
                      'How the clips are arranged inside the clips folder. The line underneath shows an example.\n\n'
                      'Clip names carry a short code for the video they came from, so two cameras that both made '
                      'a GOPR0001.MP4 never collide. Your original files are never renamed.'),
    'csv_folder': ('Save timelines to',
                   'Normally a "timelines" folder inside the clips folder. Choose somewhere else if you want them '
                   'kept apart. With timelines only, you must choose a folder.'),

    # --- advanced: processing --------------------------------------------------------------------------------------
    'phases_enabled': ('Work out the parts of each jump',
                       'Reads the picture, the sound and the camera\'s motion data to split each video into '
                       'climbing out, exit, freefall, break-off, opening, canopy flight and landing.\n\n'
                       'Off means profiles cannot choose parts of the jump; only the people settings apply.'),
    'phase_classifier': ('Model', 'Which trained model works out the parts of the jump.'),
    'device': ('Run on',
               'The graphics card is many times faster than the processor. Automatic uses it when it is there.\n\n'
               'Choosing differently never changes the result and never processes finished videos again.'),
    'batch_size': ('Graphics memory use (batch size)',
                   'How many two-second windows of video the model looks at together. Higher is slightly faster '
                   'and uses more graphics memory.\n\nLower it if a video fails with an out-of-memory message. '
                   'The result is the same at any value.'),
    'hardware_decode': ('Read videos with',
                        'Unpacking 4K video is the slowest part of processing. The graphics card can do it faster '
                        'and gives exactly the same picture.\n\n'
                        'Automatic tries the graphics card on each video and uses the processor if that video '
                        'cannot be read that way. Choose Processor only if you suspect the graphics driver.'),
    'parallel_videos': ('Videos at once',
                        'How many videos are processed side by side.\n\n'
                        '1 is the safe choice. More is faster when the machine has spare processor cores and '
                        'graphics memory, and slower when it does not, or when the videos sit on one slow drive.\n\n'
                        'Automatic starts with one and adds another only while the processor, memory and graphics '
                        'card all have room. The results are the same however many run together.'),
    'view_mode': ('360 camera footage',
                  'GoPro MAX and other 360 cameras record all round. The front view is the one the models were '
                  'trained on, and is the most accurate.\n\n"People counted all round" also looks behind the '
                  'camera when counting people. Ordinary cameras ignore this setting.'),
    'recut_on_review': ('Re-cut a video as soon as you mark it reviewed',
                        'On the Review tab, "Mark reviewed" and "Not skydiving" cut that video again straight '
                        'away from your labels.\n\nOff means your corrections are used the next time you click '
                        'Process videos.'),

    # --- advanced: people ------------------------------------------------------------------------------------------
    'people_enabled': ('Look for people in the picture',
                       'Finds the people in view once for every moment of the timeline, and measures how much of '
                       'the picture they fill.\n\nThe "people in view" and "people fill" settings of your profiles '
                       'need this. Off means those settings are ignored.'),
    'yolo_model': ('Person detector',
                   'The model that finds people in the picture.\n\n'
                   'Standard is small and fast, and was made for everyday photos, so it misses skydivers in odd '
                   'positions and at a distance. A larger one finds more of them: on test jumps the largest found '
                   'two or more people on 93% of freefall seconds against 70%, for a few milliseconds more per '
                   'look.\n\n'
                   'It does not change how much of the picture people fill: jumpers who are far away are still '
                   'small. Only the detectors whose files are in the app folder are listed.'),
    'sample_fps': ('Checks per second',
                   'How often the video is looked at for people. 1 is one look a second.\n\n'
                   'It is also how finely clips can start and end: at 1, to the nearest second; at 2, the nearest '
                   'half second. Higher values take longer.'),
    'detection_confidence': ('How sure it must be that it is a person (0 to 1)',
                             'The detector gives every find a score from 0 to 1.\n\n'
                             'Lower accepts less certain finds: more distant or half-hidden people are counted, '
                             'and so are more mistakes, such as a canopy or a cloud taken for a person. Higher '
                             'misses more real people. 0.35 is the tested value.'),
}

PHASES = {
    'inside_plane': 'In the aircraft before the door opens, and other groups getting out ahead of you.',
    'climbing_out': 'From the door opening to letting go: climbing out and setting up.',
    'exit': 'The first seconds after leaving the aircraft, until the fall has settled.',
    'freefall': 'The skydive itself, from the settled fall until people turn to leave.',
    'break_off': 'People turning and tracking away from each other before opening. Its start is a judgement, so '
                 'expect it a second or two either way.',
    'opening_parachutes': 'From the pull to a fully open canopy.',
    'canopy_flight': 'Flying the parachute, until the final approach.',
    'landing': 'The final approach and touchdown.',
    'landed': 'On the ground after landing.',
}

# Settings that are not shown as a control of their own, so they need no help entry.
UNSEEN = {'poll_seconds', 'window_geometry', 'column_state', 'open_sections', 'mode', 'advanced_enabled'}


def label(key):
    return HELP[key][0]


def text(key):
    """The explanation, with a warning when changing the setting processes a finished library again."""
    body = HELP[key][1]
    return f'{body}\n\n{REPROCESS_NOTE}' if key in reprocessing() else body


def reprocessing():
    """Settings whose change is part of the processing fingerprint, so a finished library is processed again."""
    always = {'input_folder', 'output_folder', 'keep_watching', 'profiles', 'presets', 'csv_folder'}
    changed = {f.name for f in fields(Settings) if f.metadata.get('affects_output') is not False}
    return ((changed | {f.name for f in fields(KeepProfile)}) & set(HELP)) - always


# Under canopy and on the ground the camera wearer is usually in their own picture.
SELF_IN_VIEW = ('canopy_flight', 'landing', 'landed')


def includes_you_warning(profile):
    """Said beside "people in view" when the profile keeps parts of the jump where the wearer is usually in shot."""
    if profile.min_person_count < 1 or not set(SELF_IN_VIEW) & set(profile.phases):
        return ''
    return ('This count includes you. Under canopy and on landing your own legs or arms are usually in the picture '
            'and count as one person.')


def profile_summary(profile, phases_enabled=True, people_enabled=True):
    """One sentence saying what a profile keeps."""
    names = [phase.replace('_', ' ') for phase in PHASES if phase in profile.phases]
    if not phases_enabled:
        what = 'Keeps any part of the video'
    elif not names:
        return 'Keeps nothing: no part of the jump is ticked.'
    else:
        what = 'Keeps ' + (', '.join(names[:-1]) + ' and ' + names[-1] if len(names) > 1 else names[0])
    who = []
    if people_enabled and profile.min_person_count:
        who.append(f'at least {profile.min_person_count} {"person is" if profile.min_person_count == 1 else "people are"} '
                   'in view')
    if people_enabled and profile.min_total_area_percent:
        who.append(f'people fill {profile.min_total_area_percent:g}% of the picture')
    sentence = what + (' while ' + ' and '.join(who) if who else ', whether or not anyone is in view')
    extra = []
    if profile.margin_before_seconds or profile.margin_after_seconds:
        extra.append(f'{profile.margin_before_seconds:g} s extra before and {profile.margin_after_seconds:g} s after')
    if profile.min_span_seconds:
        extra.append(f'matches under {profile.min_span_seconds:g} s ignored')
    if profile.max_gap_seconds:
        extra.append(f'gaps up to {profile.max_gap_seconds:g} s joined')
    if people_enabled and profile.people_gap_seconds:
        extra.append(f'gaps up to {profile.people_gap_seconds:g} s joined while at least {profile.people_gap_count} '
                     f'{"person is" if profile.people_gap_count == 1 else "people are"} still in view')
    return sentence + ('; ' + ', '.join(extra) if extra else '') + '.'
