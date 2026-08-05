#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_verts) return;

    int i = int(idx);

    // 获取并应用 Snapping Mask
    float mask_val = 1.0;
    if (use_mask == 1) {
        mask_val = imgLoad(img_snapping_mask, i).r;
        if (invert_mask == 1) {
            mask_val = 1.0 - mask_val;
        }
    }
    
    float force = snapping_force * mask_val;
    if (force <= 0.00001) return;

    vec3 p = imgLoad(img_pos, i).xyz;
    vec3 pp = imgLoad(img_snap_points, i).xyz;
    vec3 pn = imgLoad(img_snap_normals, i).xyz;
    vec3 v_normal = imgLoad(img_vert_normals, i).xyz;

    // 计算 cycle 以匹配 CPU 端的分时投影逻辑
    uint cycle = (idx ^ 0x243F6A88u) * 0x243F6A88u;
    cycle = cycle ^ (cycle >> 5u);
    cycle = cycle + uint(snap_count);

    vec3 target_point;
    if (cycle % uint(cycle_quality) > 0) {
        // 使用缓存的三角形平面投影，使顶点能沿着目标表面顺畅滑动而不会产生粘滞力
        vec3 v_to_anchor = p - pp;
        target_point = p - pn * dot(v_to_anchor, pn);
    } else {
        // 直接使用新更新的最近点位置（包含切向分量以贴合细节）
        target_point = pp;
    }

    vec3 snap_vec = target_point - p;
    float dist = length(snap_vec);

    if (snapping_mode == 1) {
        // --- SURFACE Mode ---
        if (dot(snap_vec, pn) > 0.0) {
            if (dot(snap_vec, v_normal) < 0.0) {
                snap_vec = v_normal * dist + snap_vec * 0.5;
            }
        }
        float dot_norm = dot(v_normal, pn);
        float snapping_weight = dot_norm * dot_norm;
        
        vec3 next_pos = p + snap_vec * force * snapping_weight;
        imgStore(img_pos, i, vec4(next_pos, 1.0));

    } else if (snapping_mode == 2 || snapping_mode == 4) {
        // --- OUTSIDE (2) or INSIDE (4) Mode ---
        bool is_outside = dot(snap_vec, pn) > 0.0;
        bool want_inside = (snapping_mode == 4);
        
        if (is_outside != want_inside) {
            imgStore(img_pos, i, vec4(pp, 1.0));
        }
    }
}
