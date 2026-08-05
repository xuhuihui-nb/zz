#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_verts) return;

    int i = int(idx);

    // 读取 Header 信息
    vec4 header = imgLoad(img_headers, i);
    int start = int(round(header.r));
    int count = int(round(header.g));

    if (count == 0) {
        imgStore(img_temp_pos, i, imgLoad(img_pos, i));
        return;
    }

    vec3 my_pos = imgLoad(img_pos, i).xyz;

    if (use_plasticity == 1) {
        // --- 软弹簧力 (Soft Spring Force with Plasticity) ---
        vec3 total_force = vec3(0.0);
        for (int j = 0; j < count; ++j) {
            int link_idx = start + j;
            vec4 link = imgLoad(img_links, link_idx);
            int neighbor = int(round(link.r));
            float rest_length = link.g;
            float scale = link.b;

            vec3 other_pos = imgLoad(img_pos, neighbor).xyz;
            vec3 delta = my_pos - other_pos;
            float curr_length = max(length(delta), 0.00001);

            float target_length = rest_length * scale;
            float diff = (target_length - curr_length) / curr_length;
            total_force += delta * diff;

            // 更新可塑性 scale
            float new_scale = curr_length / (rest_length + 0.00001);
            new_scale = clamp(new_scale, min_deform, max_deform);
            scale = mix(scale, new_scale, deform_update);
            scale = mix(scale, 1.0, deform_restore);

            // 写回更新后的 scale
            imgStore(img_links, link_idx, vec4(float(neighbor), rest_length, scale, 0.0));
        }

        vec3 next_pos = my_pos + total_force * (1.0 / (float(count) + 0.00001)) * stiffness;
        imgStore(img_temp_pos, i, vec4(next_pos, 1.0));

    } else {
        // --- 刚性弹簧力 (Stiff Spring Force) ---
        vec3 accum_pos = vec3(0.0);
        for (int j = 0; j < count; ++j) {
            int link_idx = start + j;
            vec4 link = imgLoad(img_links, link_idx);
            int neighbor = int(round(link.r));
            float rest_length = link.g;
            float scale = link.b;

            vec3 other_pos = imgLoad(img_pos, neighbor).xyz;
            vec3 delta = my_pos - other_pos;
            float curr_length = max(length(delta), 0.00001);

            float diff = (rest_length * scale) / curr_length;
            diff = mix(1.0, diff, stiffness);

            accum_pos += other_pos + delta * diff;
        }

        vec3 next_pos = accum_pos * (1.0 / float(count));
        imgStore(img_temp_pos, i, vec4(next_pos, 1.0));
    }
}
