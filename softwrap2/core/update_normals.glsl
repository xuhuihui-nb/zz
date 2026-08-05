#define imgLoad(img, idx) imageLoad(img, ivec2((idx) & 1023, (idx) >> 10))
#define imgStore(img, idx, val) imageStore(img, ivec2((idx) & 1023, (idx) >> 10), val)

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= n_items) return;

    int i = int(idx);

    if (mode == 0) {
        // --- Calculate Face Normals ---
        vec4 tri = imgLoad(img_triangles, i);
        int v0 = int(round(tri.r));
        int v1 = int(round(tri.g));
        int v2 = int(round(tri.b));

        vec3 a = imgLoad(img_pos, v0).xyz;
        vec3 b = imgLoad(img_pos, v1).xyz;
        vec3 c = imgLoad(img_pos, v2).xyz;

        vec3 normal = normalize(cross(b - a, c - a));
        imgStore(img_face_normals, i, vec4(normal, 0.0));

    } else if (mode == 1) {
        // --- Calculate Vertex Normals ---
        vec4 header = imgLoad(img_vert_tri_headers, i);
        int start = int(round(header.r));
        int count = int(round(header.g));

        if (count == 0) return;

        vec3 sum_normal = vec3(0.0);
        for (int j = 0; j < count; ++j) {
            int tri_idx = int(round(imgLoad(img_vert_tri_indices, start + j).r));
            sum_normal += imgLoad(img_face_normals, tri_idx).xyz;
        }

        sum_normal = normalize(sum_normal);
        
        vec3 old_normal = imgLoad(img_vert_normals, i).xyz;
        vec3 next_normal = mix(old_normal, sum_normal, lerp_factor);
        next_normal = normalize(next_normal);

        imgStore(img_vert_normals, i, vec4(next_normal, 0.0));
    }
}
