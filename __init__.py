bl_info = {
    "name": "Merge NLA Strips",
    "author": "Likkez",
    "version": (1, 2),
    "blender": (3, 3, 0),
    "description": "Merge multiple NLA strips into one.",
    "wiki_url": "",
    "category": "Animation",
}

import bpy
import math


BLENDER_50 = bpy.app.version >= (5, 0, 0)

if (BLENDER_50):
    from bpy_extras import anim_utils

def get_strip_fcurves(strip):
    """Get fcurves used by this NLA strip (4.x and 5.x compatible)"""
    action = strip.action

    if BLENDER_50 and strip.action_slot:
        channelbag = anim_utils.action_get_channelbag_for_slot(action, strip.action_slot)
        return channelbag.fcurves if channelbag else []

    # Blender 4.x and earlier
    return action.fcurves


def get_or_create_action_slot(action, obj):
    """Return an existing slot or create one (5.0+ only)"""
    if not BLENDER_50:
        return None

    for slot in action.slots:
        if slot.id_data == obj:
            return slot

    return action.slots.new(id_type=obj.id_type, name=obj.name)


def get_action_fcurves_for_slot(action, slot):
    """Return an fcurve container with .new() (channelbag or action.fcurves)"""
    if BLENDER_50 and slot:
        channelbag = anim_utils.action_ensure_channelbag_for_slot(action, slot)
        return channelbag.fcurves

    # Blender 4.x fallback
    return action.fcurves


class CO_OT_CaN_MergeStrips(bpy.types.Operator):
    bl_description = "Merge multiuple NLA strips into one."
    bl_idname = 'nla_tools.nla_merge_strips'
    bl_label = "Merge NLA strips"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return context.selected_nla_strips and len(context.selected_nla_strips) > 1

    def update_progress(self, wm, progress_increment):
        """Update the progress bar"""
        self.wm_progress_number_unclamped += progress_increment
        new_progress = math.ceil(self.wm_progress_number_unclamped)

        if self.wm_progress_number != new_progress:
            self.wm_progress_number = new_progress
            wm.progress_update(math.ceil(self.wm_progress_number))
            print(self.wm_progress_number)

    def add_fcurve(self, action, slot, path, k, num_keyframes):
        """Add an F-curve to the action"""
        fcurve = get_action_fcurves_for_slot(action, slot).new(data_path=path, index=k)
        fcurve.extrapolation = 'LINEAR'
        fcurve.keyframe_points.add(num_keyframes)
        return fcurve

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
        self.wm_progress_number = 0
        self.wm_progress_number_unclamped = 0
        progress_increment = 100 / ((strip_end - strip_start) * 2)
        # Collect affected F-curves and initialize dictionary
        fcurve_data = {}  # Dictionary: {data_path: [values_per_frame]}
        unresolved_fcurves = []
        for strip in selected_strips:
            for fcurve in get_strip_fcurves(strip):
                if (fcurve.data_path not in fcurve_data) and (fcurve.array_index == 0):
                    fcurve_data[fcurve.data_path] = []
        # Evaluate values at each frame and store them
        for frame in range(strip_start, strip_end):
            bpy.context.scene.frame_set(frame)
            # Progress step
            self.update_progress(wm, progress_increment)
            
            for path in list(fcurve_data.keys()):
                try:
                    value = obj.path_resolve(path).copy()
                    fcurve_data[path].append(value)
                except:
                    if path not in unresolved_fcurves:
                        unresolved_fcurves.append(path)
        # Remove the invalid fcurves
        for path in unresolved_fcurves:
            del fcurve_data[path]
        # Create merged action
        name = f"{selected_strips[0].name}_merged"
        action = bpy.data.actions.new(name=name)
        # Create slot for this object in Blender 5.0+
        action_slot = get_or_create_action_slot(action, obj)
        # Populate action F-curves
        for path, frame_values in fcurve_data.items():
            new_fcurves = []
            try:
                for k, n in enumerate(frame_values[0]):
                    new_fcurves.append(self.add_fcurve(action, action_slot, path, k, len(frame_values)))
            except:
                new_fcurves.append(self.add_fcurve(action, action_slot, path, 0, len(frame_values))) # Single index fcurve
            for frame_idx, val in enumerate(frame_values):
                for idx, new_fc in enumerate(new_fcurves):
                    new_fc.keyframe_points[frame_idx].co.x = frame_idx
                    new_fc.keyframe_points[frame_idx].interpolation = 'LINEAR'
                    try:
                        new_fc.keyframe_points[frame_idx].co.y = val[idx]
                    except:
                        new_fc.keyframe_points[frame_idx].co.y = val
            
                # Progress step
                self.update_progress(wm, progress_increment / len(fcurve_data))
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
    
        # Assign the slot to the strip in Blender 5.0+
        if action_slot and hasattr(strip, 'action_slot'):
            strip.action_slot = action_slot
        # Restore user scene frame
        bpy.context.scene.frame_set(begin_frame)
        return {'FINISHED'}


class CO_OT_CaN_RenameStrip(bpy.types.Operator):
    bl_description = "Rename selected NLA strips and its actions"
    bl_idname = 'nla_tools.nla_rename_strip'
    bl_label = "Rename NLA Strips Actions"
    bl_options = {'REGISTER', 'UNDO'}
    
    # Properties
    new_name: bpy.props.StringProperty(
        name="New Name",
        description="New name for the action and optionally the strip",
        default="Action"
    )
    
    rename_strip: bpy.props.BoolProperty(
        name="Rename Strip",
        description="Also rename the strip itself (not just the action)",
        default=True
    )
    
    rename_track: bpy.props.BoolProperty(
        name="Rename Track",
        description="Also rename the track containing the strip",
        default=False
    )
    
    handle_conflicts: bpy.props.BoolProperty(
        name="Handle Name Conflicts",
        description="Automatically rename existing actions and strips that occupy the target name",
        default=True
    )
    
    @classmethod
    def poll(cls, context):
        return context.selected_nla_strips and len(context.selected_nla_strips) >= 1
    
    def invoke(self, context, event):
        # Get the first selected strip to populate default name
        if context.selected_nla_strips:
            strip = context.selected_nla_strips[0]
            if strip.action:
                self.new_name = strip.action.name
            else:
                self.new_name = strip.name
        
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name")
        layout.prop(self, "rename_strip")
        layout.prop(self, "rename_track")
        layout.prop(self, "handle_conflicts")
    
    def get_unique_name(self, base_name, existing_names):
        """Generate a unique name by appending a number if necessary"""
        if base_name not in existing_names:
            return base_name
        
        counter = 1
        while f"{base_name}.{counter:03d}" in existing_names:
            counter += 1
        return f"{base_name}.{counter:03d}"
    
    def execute(self, context):
        if not self.new_name.strip():
            self.report({'ERROR'}, "Name cannot be empty")
            return {'CANCELLED'}
        
        renamed_count = 0
        action_conflicts_resolved = 0
        strip_conflicts_resolved = 0
        tracks_renamed = 0
        
        # Get all actions and strips that will be renamed to avoid conflicts
        actions_to_rename = []
        strips_to_rename = []
        tracks_to_rename = []
        
        # Build a map of strips to their parent tracks
        strip_to_track = {}
        obj = context.selected_nla_strips[0].id_data
        if obj.animation_data and obj.animation_data.nla_tracks:
            for track in obj.animation_data.nla_tracks:
                for strip in track.strips:
                    strip_to_track[strip] = track
        
        for strip in context.selected_nla_strips:
            if strip.action:
                actions_to_rename.append(strip.action)
            if self.rename_strip:
                strips_to_rename.append(strip)
            if self.rename_track and strip in strip_to_track:
                track = strip_to_track[strip]
                if track not in tracks_to_rename:
                    tracks_to_rename.append(track)
        
        if not actions_to_rename:
            self.report({'WARNING'}, "No strips with actions found to rename")
            return {'CANCELLED'}
        
        # Handle name conflicts if enabled
        if self.handle_conflicts:
            # Handle action name conflicts
            existing_action = bpy.data.actions.get(self.new_name)
            if existing_action and existing_action not in actions_to_rename:
                # Generate a unique name for the conflicting action
                existing_names = {action.name for action in bpy.data.actions}
                backup_name = self.get_unique_name(f"{existing_action.name}", existing_names)
                
                # Rename the conflicting action
                existing_action.name = backup_name
                action_conflicts_resolved += 1
            
            # Handle strip name conflicts if we're renaming strips
            if self.rename_strip:
                # Get all NLA strips from all objects to check for conflicts
                all_strips = []
                for obj in bpy.data.objects:
                    if obj.animation_data and obj.animation_data.nla_tracks:
                        for track in obj.animation_data.nla_tracks:
                            all_strips.extend(track.strips)
                
                # Find conflicting strips (not in our selected list)
                conflicting_strips = [strip for strip in all_strips 
                                    if strip.name == self.new_name and strip not in strips_to_rename]
                
                if conflicting_strips:
                    existing_strip_names = {strip.name for strip in all_strips}
                    
                    for conflicting_strip in conflicting_strips:
                        backup_name = self.get_unique_name(f"{conflicting_strip.name}", existing_strip_names)
                        conflicting_strip.name = backup_name
                        existing_strip_names.add(backup_name)  # Update the set for next iteration
                        strip_conflicts_resolved += 1
        
        # Now rename all selected actions and strips
        for strip in context.selected_nla_strips:
            if strip.action:
                # Rename the action
                strip.action.name = self.new_name
                renamed_count += 1
                
                # Optionally rename the strip itself
                if self.rename_strip:
                    strip.name = self.new_name
        
        # Rename tracks if requested
        if self.rename_track:
            for track in tracks_to_rename:
                track.name = self.new_name
                tracks_renamed += 1
        
        # Report results
        message_parts = []
        
        if renamed_count > 0:
            message_parts.append(f"Renamed {renamed_count} strip(s)")
        
        if tracks_renamed > 0:
            message_parts.append(f"{tracks_renamed} track(s)")
        
        total_conflicts = action_conflicts_resolved + strip_conflicts_resolved
        if total_conflicts > 0:
            conflict_details = []
            if action_conflicts_resolved > 0:
                conflict_details.append(f"{action_conflicts_resolved} action(s)")
            if strip_conflicts_resolved > 0:
                conflict_details.append(f"{strip_conflicts_resolved} strip(s)")
            
            message_parts.append(f"resolved conflicts for {' and '.join(conflict_details)}")
        
        message = " and ".join(message_parts)
        self.report({'INFO'}, message)
        return {'FINISHED'}


def MergeStrips_ContextMenu(self, context):
    layout = self.layout
    layout.operator_context = 'INVOKE_DEFAULT'
    layout.operator(CO_OT_CaN_MergeStrips.bl_idname)
    layout.operator(CO_OT_CaN_RenameStrip.bl_idname)


classes = (
    CO_OT_CaN_MergeStrips,
    CO_OT_CaN_RenameStrip,
)

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