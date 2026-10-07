"""Every setting's name and its explanation, in one place.

The window, the profile editor and the tests all read this, so a label and its help cannot drift apart, and a
setting cannot be added without saying what it does (tests/app/test_help.py).

Each entry is ``key: (label, help)``. Keys named after a ``Settings`` or ``KeepProfile`` field belong to that field.
Help is plain text; a blank line starts a new paragraph.
"""
from dataclasses import fields, replace

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
               'a full path, such as D:\\Best of the day, to put this profile\'s clips somewhere else entirely.'),

    # --- basic mode: the three built-in choices --------------------------------------------------------------------
    'basic_trim': ('Trim my video',
                   'For the end of the day: you want to keep your jumps without keeping everything the camera '
                   'recorded.\n\n'
                   'Each video is cut down to the jump itself: exit, freefall, break-off and the opening. The clip '
                   'starts a couple of seconds before exit and ends when the canopy is open. Time in the plane, '
                   'canopy flight and the walk back are left out, so the clip is a fraction of the size of the '
                   'original.\n\n'
                   'It keeps the whole jump whether or not anyone is in view, and it does not look for people, so '
                   'it is the fastest choice.\n\n'
                   'Tick the landing to get a second clip of the final approach and touchdown. Both numbers can be '
                   'as large as you like.\n\n'
                   'Your original videos are never changed or deleted. Clips go into a "Trimmed" folder, named '
                   'after each video.'),
    'basic_a': ('A grade video',
                'A grade and B grade are about how good the video is. A grade is the best of it: the moments where '
                'at least 1 person is in view and fills at least 20% of the picture, from exit to the end of '
                'break-off. Professional video shot by a cameraman would count as A grade.\n\n'
                'If you are putting together a video of the day, start here. If A grade gives you enough, use '
                'only that. If it does not, add B grade.\n\n'
                'Include the exit: on exit everyone is in view until they let go, so nearly every jump gives an '
                'exit clip. Untick it if you end up with more exits than you want; A grade then starts at '
                'freefall.\n\n'
                'Include canopy flight: also keeps canopy flight with at least 2 people filling 20%. That count '
                'includes you: your own legs or arms in the picture are one of the two.\n\n'
                'Drop-outs of up to 2 seconds are joined, moments shorter than 2 seconds are ignored, and each '
                'clip gets 2 seconds extra at each end.\n\n'
                'Clips go into an "A grade" folder, named after each video.'),
    'basic_b': ('B grade video',
                'Video that is not as good as A grade, for when A grade alone does not give you enough.\n\n'
                'It keeps everything A grade keeps, plus video a wandering camera would lose: people need fill '
                'only 10% of the picture, gaps of up to 6 seconds are joined, and gaps of up to 10 seconds are '
                'joined while at least 3 people are still in view.\n\n'
                'B grade always includes the exit, whatever A grade\'s exit tick says.\n\n'
                'Each clip gets 2 seconds extra before and 3 seconds after. Clips go into a "B grade" folder, '
                'named after each video. Because B includes A, the same freefall will be in both folders when '
                'both are ticked.'),

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
    'check_updates': ('Check for a newer version when the app starts',
                      'Once at start-up the app asks GitHub, where Skydive Cutter is published, for the number of '
                      'the latest version. If yours is older, a line at the top of the window says so, with a '
                      'button that opens the download page.\n\n'
                    'Nothing about your PC or your videos is sent, and nothing is downloaded or installed for '
                      'you. Without an internet connection the app simply says nothing.'),

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

# What the app does between "Process videos" and the clips appearing, said in one place behind one button. The numbers
# are read from the built-in profiles, so the words cannot drift from what the app does.
RULES_TITLE = 'How video is chosen in basic mode'
STAGES = ('In the plane', 'Climbing out', 'Exit', 'Freefall', 'Break-off', 'Opening', 'Canopy flight', 'Landing',
          'Landed')
SOUND_EXTENDS_FREEFALL_SECONDS = 30   # cutter_v4.engine.AUDIO_FREEFALL_MAX_EXTENSION; a test keeps the two the same

# The jump followed through every step at the end of the note. Times are seconds into a six-minute video.
EXAMPLE_DURATION = 360
EXAMPLE_STAGES = (('inside_plane', 0, 182), ('climbing_out', 182, 190), ('exit', 190, 196), ('freefall', 196, 245),
                  ('break_off', 245, 250), ('opening_parachutes', 250, 255), ('canopy_flight', 255, 360))
EXAMPLE_CLOSE = ((190, 194), (205, 220), (221, 238), (242, 243))   # when someone fills 20% or more of the picture


def clock(seconds):
    return f'{int(seconds) // 60}:{int(seconds) % 60:02d}'


def seconds_word(value):
    return f'{value:g} second' + ('' if value == 1 else 's')


def rules():
    """The note as blocks: ('title', words), ('text', words), ('list', [words]) or ('table', [(left, right)])."""
    from app.settings import A_GRADE, B_GRADE, TRIM, built_in_profiles
    built = built_in_profiles()
    trim, a, b = built[TRIM], built[A_GRADE], built[B_GRADE]
    stage_rows = [(f'{clock(start)} to {clock(end)}', PHASE_NAMES[phase]) for phase, start, end in EXAMPLE_STAGES[:-1]]
    stage_rows.append((f'{clock(EXAMPLE_STAGES[-1][1])} to {clock(EXAMPLE_DURATION)}', 'Canopy flight, landing, landed'))
    return [
        ('text', 'This page explains what the app does to a video between you clicking Process videos and the clips '
                 'appearing in your folder. It describes the three choices on the Basic screen. Advanced mode uses '
                 'the same steps but gives you more control: you can build your own profiles and set every number '
                 'mentioned below yourself.'),
        ('text', 'There are four steps. The app labels each second of the video, counts the people in each second, '
                 'decides which seconds each choice wants to keep, and then turns those seconds into clips.'),

        ('title', 'Step 1: The app labels every second with a stage of the jump'),
        ('text', 'The app watches the whole video and gives every second one label. There are nine labels, which we '
                 'call stages:'),
        ('list', [f'{number}. {name}' for number, name in enumerate(STAGES, 1)]),
        ('text', 'To do this it uses three things: the picture, the sound, and the motion data that some cameras '
                 'record (GoPro and DJI cameras, for example).'),
        ('text', 'The stages only go forwards. A skydive always happens in the order above, so the app is not '
                 'allowed to go back to an earlier stage. Once it has decided you have exited, no later second can '
                 'be labelled "in the plane", even if the picture looks like the inside of a plane for a moment. '
                 'Once your canopy is open, no later second can be labelled freefall. This rule stops the app from '
                 'making silly mistakes, such as deciding you were in freefall for two seconds in the middle of '
                 'your canopy ride.'),
        ('text', 'A stage can be missing. If you press record after you have already left the plane, the video has '
                 'no "in the plane", no "climbing out" and no "exit". That is fine. The app skips them and starts at '
                 'freefall.'),
        ('text', 'The app expects one jump per video. This follows from the forwards-only rule. If one file '
                 'contains two jumps, the second jump would need the stages to start again from the beginning, '
                 'which is not allowed. The app will find one of the jumps and get the other wrong. If your camera '
                 'recorded two jumps in one file, split the file into two before processing it.'),
        ('text', 'How sound is used. The picture is what decides the stages. Sound is allowed to change the answer '
                 'in one situation only. If your camera does not record motion data, and the picture says freefall '
                 'has ended but the sound of the wind says you are still falling, the app keeps freefall going for '
                 f'up to {SOUND_EXTENDS_FREEFALL_SECONDS} more seconds. This is because, in testing, the picture '
                 'sometimes ended freefall too early on these cameras.'),
        ('text', 'In every other case, sound and motion are used only as a second opinion. If they disagree with '
                 'the picture, the answer does not change, but the Review tab shows that part of the video in amber '
                 'so you know where to look.'),
        ('text', 'Break-off is the least exact stage. When exactly a group starts to break off is a matter of '
                 'opinion, and two people watching the same video will often disagree by a second or two. So expect '
                 'the end of freefall to be a second or two early or late. This is why each choice adds a little '
                 'extra video at the end of every clip.'),

        ('title', 'Step 2: The app counts the people in every second'),
        ('text', 'Once a second, the app looks at the picture and finds the people in it. It draws a box around '
                 'each person and records two numbers for that second:'),
        ('list', ['How many people it found.',
                  'How much of the picture they fill, as a percentage. This is the area of all the boxes added '
                  'together.']),
        ('text', 'To give you a feel for the second number: one person close to the camera fills about 20% of the '
                 'picture. A jumper on the far side of a formation might fill only 1% to 3%.'),
        ('text', 'You (the camera person) count as a person. Under canopy and on landing, your own legs and arms '
                 'can be in shot, and the app counts them as one person. So "2 people in view" under canopy usually '
                 'means you and one other.'),
        ('text', 'The count of people never changes the classification of stages. Step 1 is finished before the '
                 'people are looked at. The people count only decides which seconds of a stage are worth keeping.'),
        ('text', 'Trim my video skips this step completely, because it does not care who is in the picture. That '
                 'is why it is the fastest choice.'),

        ('title', 'Step 3: Each choice decides which seconds match its criteria'),
        ('text', 'The app now has, for every second, a stage and a people count. Each choice you ticked goes '
                 'through the video and marks the seconds that match its criteria.'),
        ('text', 'Trim my video matches every second that is in exit, freefall, break-off or opening. It does not '
                 'look at people at all.'),
        ('text', 'A grade video matches a second when both of these are true:'),
        ('list', ['The second is in exit, freefall or break-off (or only freefall and break-off, if you unticked '
                  '"Include the exit").',
                  f'At least {a.min_person_count} person is in view and people fill at least '
                  f'{a.min_total_area_percent:g}% of the picture.']),
        ('text', 'B grade video uses the same stages as A grade, always with the exit included, but people only '
                 f'need to fill {b.min_total_area_percent:g}% of the picture.'),

        ('title', 'Step 4: The matching seconds are then turned into clips'),
        ('text', 'The matching seconds are rarely one neat block. Someone drifts out of shot for a second, or the '
                 'camera looks away. So the app tidies up, always in this order.'),
        ('text', 'First, short gaps are filled in. This only matters for A grade and B grade. If there is matching '
                 'video, then a short gap, then more matching video, the gap is filled so you get one clip instead '
                 f'of two. A grade fills gaps of up to {seconds_word(a.max_gap_seconds)}. B grade fills gaps of up '
                 f'to {seconds_word(b.max_gap_seconds)}, and up to {seconds_word(b.people_gap_seconds)} if at least '
                 f'{b.people_gap_count} people stayed in view during the gap, even if they were small in the '
                 'picture.'),
        ('text', 'Trim my video has no gaps to fill: the stages it keeps always follow straight on from each '
                 'other, so it is always one clip.'),
        ('text', 'A gap is only filled when there is matching video on both sides of it. Filling gaps never makes '
                 'a clip start earlier or end later.'),
        ('text', 'Second, short matches that stand alone are dropped (A grade and B grade only). After the gaps '
                 f'are filled, anything still shorter than {seconds_word(a.min_span_seconds)} is thrown away. This '
                 'only removes a brief glimpse of someone with nothing else near it. A run of short matches close '
                 'together has already been joined into one longer match by the first step, so it is kept.'),
        ('text', 'Third, extra seconds are added to each end. This gives each clip a lead-in and covers the '
                 f'uncertainty about where break-off ends. A grade adds {seconds_word(a.margin_before_seconds)} '
                 f'before and {a.margin_after_seconds:g} after. B grade adds {b.margin_before_seconds:g} before and '
                 f'{b.margin_after_seconds:g} after. Trim my video adds the seconds you chose before the exit, and '
                 f'{seconds_word(trim.margin_after_seconds)} after the canopy is open.'),
        ('text', 'Fourth, clips that now touch are joined. If adding the extra seconds makes two clips overlap, or '
                 'leaves them less than a second apart, they become one clip.'),
        ('text', 'Last, the clip is cut from your original video. The app copies that part of the file without '
                 're-encoding it. This is quick, and the clip has exactly the quality of your original. The one '
                 'side effect is that a copy can only begin at certain frames in the original, called keyframes. So '
                 'a clip may start a second or two earlier than the app planned. It is never shorter than planned.'),

        ('title', 'An example'),
        ('text', f'Say you film a 4-way and the video is {EXAMPLE_DURATION // 60} minutes long. The app labels it '
                 'like this:'),
        ('table', stage_rows),
        ('text', f'Trim my video keeps exit through opening, {clock(190)} to {clock(255)}. With '
                 f'{seconds_word(trim.margin_before_seconds)} added before and {trim.margin_after_seconds:g} after, '
                 f'you get one clip from {clock(188)} to {clock(256)}. A {EXAMPLE_DURATION // 60} minute video has '
                 'become a 68 second clip.'),
        ('text', 'A grade video also looks at the people. Suppose someone is close to the camera (filling 20% or '
                 'more of the picture) at these times:'),
        ('list', [f'{clock(190)} to {clock(194)}, on the exit', f'{clock(205)} to {clock(220)}',
                  f'{clock(221)} to {clock(238)}', f'{clock(242)} to {clock(243)}']),
        ('text', 'Here is what happens:'),
        ('list', [f'The gap between {clock(220)} and {clock(221)} is 1 second, so it is filled. That gives one '
                  f'match from {clock(205)} to {clock(238)}.',
                  f'The gap between {clock(194)} and {clock(205)} is 11 seconds, which is too long to fill. The '
                  'exit stays separate.',
                  f'The match at {clock(242)} lasts 1 second and stands alone, so it is dropped.',
                  'Two seconds are added to each end of what is left.']),
        ('text', f'You get two clips: {clock(188)} to {clock(196)} (the exit) and {clock(203)} to {clock(240)} '
                 '(the freefall). If you had unticked "Include the exit", you would get only the second one.'),
        ('text', 'B grade video would give you more from the same jump, because people only need to fill '
                 f'{b.min_total_area_percent:g}% of the picture and longer gaps are filled.'),

        ('title', 'The exact numbers for each choice'),
    ]


PHASE_NAMES = {'inside_plane': 'In the plane', 'climbing_out': 'Climbing out', 'exit': 'Exit',
               'freefall': 'Freefall', 'break_off': 'Break-off', 'opening_parachutes': 'Opening',
               'canopy_flight': 'Canopy flight', 'landing': 'Landing', 'landed': 'Landed'}


# The opening sentences that are the points being made; the note shows them in bold.
RULE_LEADS = ('The stages only go forwards.', 'A stage can be missing.', 'The app expects one jump per video.',
              'How sound is used.', 'Break-off is the least exact stage.',
              'You (the camera person) count as a person.',
              'The count of people never changes the classification of stages.',
              'First, short gaps are filled in.',
              'Second, short matches that stand alone are dropped (A grade and B grade only).',
              'Third, extra seconds are added to each end.', 'Fourth, clips that now touch are joined.',
              'Last, the clip is cut from your original video.')


def rules_text():
    """The note as plain text, a blank line between blocks."""
    said = []
    for kind, content in rules():
        if kind == 'list':
            said.append('\n'.join(content))
        elif kind == 'table':
            said.append('\n'.join(f'{left}: {right}' for left, right in content))
        else:
            said.append(content)
    return '\n\n'.join(said)


def built_in_choices():
    """[(title, what it keeps)] for each built-in choice, read from the profiles themselves so it cannot drift."""
    from app.settings import A_CANOPY, A_GRADE, B_GRADE, LANDING, TRIM, built_in_profiles
    built = built_in_profiles()
    return [(title, profile_summary(replace(built[name], enabled=True)))
            for title, name in ((label('basic_trim'), TRIM), ('Its landing', LANDING), (label('basic_a'), A_GRADE),
                                ('Its canopy flight', A_CANOPY), (label('basic_b'), B_GRADE))]


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
