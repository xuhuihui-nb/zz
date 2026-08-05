#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_verts) return;

    int i = int(idx);

    // 读取 Header 信息
    vec4 header = imgLoad(img_vertex_quad_headers, i);
    int start = int(round(header.r));
    int count = int(round(header.g));

    if (count == 0) {
        imgStore(img_temp_pos, i, imgLoad(img_pos, i));
        return;
    }

    vec3 my_pos = imgLoad(img_pos, i).xyz;
    vec3 total_offset = vec3(0.0);
    float min_ratio = 1.0 / max_ratio;

    for (int j = 0; j < count; ++j) {
        int v_link_idx = start + j;
        vec4 v_link = imgLoad(img_vertex_quad_links, v_link_idx);
        int link_idx = int(round(v_link.r));
        int role = int(round(v_link.g));

        // 读取 Quaternary Link 属性
        vec4 indices = imgLoad(img_quad_indices, link_idx);
        int qa = int(round(indices.r));
        int qb = int(round(indices.g));
        int qc = int(round(indices.b));
        int qd = int(round(indices.a));

        vec4 params = imgLoad(img_quad_params, link_idx);
        float ratio = params.r;
        float side = params.g; // Unused or used for orientation, if needed

        if (ratio < min_ratio || ratio > max_ratio) {
            continue;
        }

        vec3 pa = imgLoad(img_pos, qa).xyz;
        vec3 pb = imgLoad(img_pos, qb).xyz;
        vec3 pc = imgLoad(img_pos, qc).xyz;
        vec3 pd = imgLoad(img_pos, qd).xyz;

        vec3 ab = pa - pb;
        vec3 cd = pc - pd;

        float rlab = max(length(ab), 0.00001);
        float rlcd = max(length(cd), 0.00001);

        float lab = rlcd * ratio;
        float lcd = rlab / ratio;

        vec3 ab_diff = ab - (ab / rlab) * lab;
        vec3 cd_diff = cd - (cd / rlcd) * lcd;

        if (role == 0) {
            total_offset -= ab_diff;
        } else if (role == 1) {
            total_offset += ab_diff;
        } else if (role == 2) {
            total_offset -= cd_diff;
        } else if (role == 3) {
            total_offset += cd_diff;
        }
    }

    vec3 next_pos = my_pos + total_offset * factor / float(count);
    imgStore(img_temp_pos, i, vec4(next_pos, 1.0));
}
