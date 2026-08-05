#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_verts) return;

    int i = int(idx);

    vec3 my_pos = imgLoad(img_pos, i).xyz;
    vec4 symm = imgLoad(img_symm_map, i);
    int symm_x_idx = int(round(symm.r));
    int symm_y_idx = int(round(symm.g));
    int symm_z_idx = int(round(symm.b));

    vec3 next_pos = my_pos;

    if (mirror_x == 1) {
        vec3 v = imgLoad(img_pos, symm_x_idx).xyz;
        v.x = -v.x;
        next_pos = (next_pos + v) * 0.5;
    }
    if (mirror_y == 1) {
        vec3 v = imgLoad(img_pos, symm_y_idx).xyz;
        v.y = -v.y;
        next_pos = (next_pos + v) * 0.5;
    }
    if (mirror_z == 1) {
        vec3 v = imgLoad(img_pos, symm_z_idx).xyz;
        v.z = -v.z;
        next_pos = (next_pos + v) * 0.5;
    }

    imgStore(img_temp_pos, i, vec4(next_pos, 1.0));
}
