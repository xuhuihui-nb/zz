#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_verts) return;

    int i = int(idx);
    vec3 my_pos = imgLoad(img_pos, i).xyz;

    if (mode == 0) {
        // --- Laplacian Smooth ---
        vec4 header = imgLoad(img_headers, i);
        int start = int(round(header.r));
        int count = int(round(header.g));

        if (count == 0) {
            imgStore(img_temp_pos, i, vec4(my_pos, 1.0));
            return;
        }

        vec3 avg = vec3(0.0);
        for (int j = 0; j < count; ++j) {
            int link_idx = start + j;
            int neighbor = int(round(imgLoad(img_links, link_idx).r));
            avg += imgLoad(img_pos, neighbor).xyz;
        }
        avg /= float(count);

        vec3 next_pos = mix(my_pos, avg, factor);
        imgStore(img_temp_pos, i, vec4(next_pos, 1.0));

    } else if (mode == 1) {
        // --- Ternary Topological Smooth ---
        vec4 t_header = imgLoad(img_ternary_headers, i);
        int start = int(round(t_header.r));
        int count = int(round(t_header.g));

        if (count == 0) {
            imgStore(img_temp_pos, i, vec4(my_pos, 1.0));
            return;
        }

        vec3 accum = vec3(0.0);
        vec3 normal = imgLoad(img_normals, i).xyz;

        for (int j = 0; j < count; ++j) {
            int link_idx = start + j;
            vec4 t_link = imgLoad(img_ternary_links, link_idx);
            int a = int(round(t_link.r));
            int b = int(round(t_link.g));
            bool side = t_link.b > 0.5;
            float avg_dist = t_link.a;

            vec3 pa = imgLoad(img_pos, a).xyz;
            vec3 pb = imgLoad(img_pos, b).xyz;

            vec3 avg = (pa + pb) * 0.5;
            vec3 d = my_pos - avg;

            bool current_side = dot(d, normal) > 0.0;

            if (current_side != side) {
                // 反射法线方向的位移
                d = d - normal * dot(d, normal) * 2.0;
            }

            float len_d = length(d);
            float len_ab = length(pa - pb);
            if (len_d > 0.00001) {
                d = d * (avg_dist * len_ab / len_d);
            } else {
                d = vec3(0.0);
            }

            accum += avg + d;
        }

        vec3 target_pos = accum * (1.0 / float(count));
        vec3 next_pos = mix(my_pos, target_pos, factor);
        imgStore(img_temp_pos, i, vec4(next_pos, 1.0));
    }
}
