bl_info = {
    "name": "Merge NLA Strips",
    "author": "Likkez",
    "version": (1, 0),
    "blender": (3, 3, 0),
    "description": "Merge multiple NLA strips into one.",
    "wiki_url": "",
    "category": "Animation",
}

import bpy
import math


class CO_OT_CaN_MergeStrips(bpy.types.Operator):
    bl_description = "Merge multiuple NLA strips into one."
    bl_idname = 'nla_tools.nla_merge_strips'
    bl_label = "Merge NLA strips"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return context.selected_nla_strips and len(context.selected_nla_strips) > 1

    def execute(self, context):
        obj = bpy.context.selected_nla_strips[0].id_data
        wm = bpy.context.window_manager

        begin_frame = context.scene.frame_current

        selected_strips = []
        strip_mode = 'COMBINE'
        strip_start = math.inf
        strip_end = -math.inf
        disabled_tracks = []
        track_min_idx = math.inf

        # Gather selected strips and calculate the overall range
        for i, track in enumerate(obj.animation_data.nla_tracks):
            found = False
            for strip in track.strips:
                if strip.select:
                    found = True
                    selected_strips.append(strip)
                    disabled_tracks.append(track)

                    strip_start = min(strip_start, math.floor(strip.frame_start))
                    strip_end = max(strip_end, math.ceil(strip.frame_end))

                    if strip.blend_type == 'REPLACE' or strip_mode != 'REPLACE':
                        strip_mode = strip.blend_type
            if found:
                track_min_idx = min(track_min_idx, i)

        # Disable tracks that would get in the way of baking.
        for i, track in enumerate(obj.animation_data.nla_tracks):
            if (not (track.mute or (track in disabled_tracks))) and \
            not ((strip_mode == 'REPLACE') and (i < track_min_idx)):
                disabled_tracks.append(track)
                track.mute = True

        # Initialize progress bar
        wm.progress_begin(0, 100)
        wm_progress_number = 0
        wm_progress_number_unclamped = 0
        progress_increment = 100 / ((strip_end - strip_start) * 2)

        def update_progress(progress_increment):
            nonlocal wm_progress_number, wm_progress_number_unclamped
            wm_progress_number_unclamped += progress_increment
            new_progress = math.ceil(wm_progress_number_unclamped)

            if wm_progress_number != new_progress:
                wm_progress_number = new_progress
                wm.progress_update(math.ceil(wm_progress_number))
                print(wm_progress_number)

        # Collect affected F-curves
        affected_fcurves = []
        for strip in selected_strips:
            for fcurve in strip.action.fcurves:
                if (not fcurve.data_path in affected_fcurves) and (fcurve.array_index == 0):
                    affected_fcurves.append(fcurve.data_path)

        # Evaluate values at each frame and store them
        fcurve_values = []
        for frame in range(strip_start, strip_end):
            bpy.context.scene.frame_set(frame)

            # Progress step
            update_progress(progress_increment)

            vals = []
            for path in affected_fcurves:
                try:
                    vals.append(obj.path_resolve(path).copy())
                except:
                    vals.append(obj.path_resolve(path))
            fcurve_values.append(vals)

        # Create merged action
        name = f"{selected_strips[0].name}_merged"
        action = bpy.data.actions.new(name=name)

        def add_fcurve(action, k):
            fcurve = action.fcurves.new(data_path=path, index=k)
            fcurve.extrapolation='LINEAR'
            fcurve.keyframe_points.add(len(fcurve_values))
            return fcurve

        # Populate action F-curves
        for i, path in enumerate(affected_fcurves):
            fcurve_type = None
            new_fcurves = []

            try:
                for k,n in enumerate(fcurve_values[0][i]):
                    new_fcurves.append(add_fcurve(action, k))
            except:
                new_fcurves.append(add_fcurve(action, 0)) # Single index fcurve

            for frame, frame_values in enumerate(fcurve_values):
                # Progress step
                update_progress(progress_increment / len(affected_fcurves))

                val = frame_values[i]
                for idx, new_fc in enumerate(new_fcurves):
                    new_fc.keyframe_points[frame].co.x = frame
                    new_fc.keyframe_points[frame].interpolation = 'LINEAR'
                    try:
                        new_fc.keyframe_points[frame].co.y = val[idx]
                    except:
                        new_fc.keyframe_points[frame].co.y = val


        wm.progress_end()

        # Find top track and re-enable disabled tracks
        prev_track = None
        for track in obj.animation_data.nla_tracks:
            if track in disabled_tracks:
                track.mute = False

            for strip in track.strips:
                if strip.select:
                    strip.mute = True
                    prev_track = track

        new_track = obj.animation_data.nla_tracks.new(prev=prev_track)
        new_track.name = action.name
        strip = new_track.strips.new(name=name, start=strip_start, action=action)
        strip.blend_type = strip_mode

        # Restore user scene frame
        bpy.context.scene.frame_set(begin_frame)

        return {'FINISHED'}


def MergeStrips_ContextMenu(self, context):
    layout = self.layout
    layout.operator(CO_OT_CaN_MergeStrips.bl_idname)


classes = (CO_OT_CaN_MergeStrips,)

def register():
    from bpy.utils import register_class
    bpy.types.NLA_MT_context_menu.append(MergeStrips_ContextMenu)
    for cls in classes:
        register_class(cls)


def unregister():
    from bpy.utils import unregister_class
    bpy.types.NLA_MT_context_menu.remove(MergeStrips_ContextMenu)
    for cls in reversed(classes):
        unregister_class(cls)


if __name__ == "__main__":
    register()
