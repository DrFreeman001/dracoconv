// Lit un fichier STEP, le découpe en triangles et écrit un maillage compact pour l'aperçu.
// Usage : step_mesh.exe <entrée.step> <sortie.mesh>
// Sortie : "DCMESH1\0", uint32 sommets, uint32 triangles, float32[sommets*3], uint32[triangles*3].
// Codes de sortie : 0 réussi, 1 arguments, 2 lecture STEP, 3 aucune surface, 4 limite, 5 écriture, 6 exception.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <cstdint>
#include <algorithm>
#include <exception>
#include <string>
#include <vector>
#include <STEPControl_Reader.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>
#include <BRep_Tool.hxx>
#include <Poly_Triangulation.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <Standard_Failure.hxx>

static const uint32_t MAX_VERTICES = 20000000, MAX_FACES = 30000000;

static std::string utf8(const wchar_t* text) {
    int n = WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
    std::string out(n > 0 ? n - 1 : 0, '\0');
    if (n > 1) WideCharToMultiByte(CP_UTF8, 0, text, -1, out.data(), n, nullptr, nullptr);
    return out;
}

static int write_mesh(const wchar_t* path, const std::vector<float>& points, const std::vector<uint32_t>& faces) {
    std::wstring part = std::wstring(path) + L".part";
    FILE* f = nullptr;
    if (_wfopen_s(&f, part.c_str(), L"wb") || !f) return 5;
    uint32_t header[2] = {uint32_t(points.size() / 3), uint32_t(faces.size() / 3)};
    bool ok = fwrite("DCMESH1", 1, 8, f) == 8 && fwrite(header, 4, 2, f) == 2 &&
              fwrite(points.data(), 4, points.size(), f) == points.size() &&
              fwrite(faces.data(), 4, faces.size(), f) == faces.size();
    ok = fclose(f) == 0 && ok;
    if (!ok || !MoveFileExW(part.c_str(), path, MOVEFILE_REPLACE_EXISTING)) {
        DeleteFileW(part.c_str());
        return 5;
    }
    return 0;
}

static int run(const wchar_t* input, const wchar_t* output) {
    TopoDS_Shape shape;
    {
        // Le lecteur garde tout le graphe STEP en mémoire : il est libéré avant le maillage.
        STEPControl_Reader reader;
        if (reader.ReadFile(utf8(input).c_str()) != IFSelect_RetDone) return 2;
        if (reader.TransferRoots() <= 0) return 3;
        shape = reader.OneShape();
    }
    if (shape.IsNull()) return 3;
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    if (box.IsVoid()) return 3;
    double x0, y0, z0, x1, y1, z1;
    box.Get(x0, y0, z0, x1, y1, z1);
    double size = (std::max)({x1 - x0, y1 - y0, z1 - z0});
    if (!(size > 0)) return 3;
    // Flèche de 0,1 % de la plus grande dimension, angle 0,5 rad, en parallèle.
    BRepMesh_IncrementalMesh mesher(shape, size * 0.001, false, 0.5, true);
    std::vector<float> points;
    std::vector<uint32_t> faces;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face& face = TopoDS::Face(it.Current());
        TopLoc_Location location;
        Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(face, location);
        if (tri.IsNull()) continue;
        const gp_Trsf transform = location.Transformation();
        const size_t base = points.size() / 3;
        const int nodes = tri->NbNodes(), triangles = tri->NbTriangles();
        if (base + nodes > MAX_VERTICES || faces.size() / 3 + triangles > MAX_FACES) return 4;
        for (int i = 1; i <= nodes; ++i) {
            gp_Pnt p = tri->Node(i).Transformed(transform);
            points.push_back(float(p.X()));
            points.push_back(float(p.Y()));
            points.push_back(float(p.Z()));
        }
        const bool reversed = face.Orientation() == TopAbs_REVERSED;
        for (int i = 1; i <= triangles; ++i) {
            int a, b, c;
            tri->Triangle(i).Get(a, b, c);
            if (a < 1 || b < 1 || c < 1 || a > nodes || b > nodes || c > nodes) return 6;
            faces.push_back(uint32_t(base + a - 1));
            faces.push_back(uint32_t(base + (reversed ? c : b) - 1));
            faces.push_back(uint32_t(base + (reversed ? b : c) - 1));
        }
    }
    if (faces.empty()) return 3;
    return write_mesh(output, points, faces);
}

int wmain(int argc, wchar_t** argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    if (argc != 3) {
        fwprintf(stderr, L"usage: step_mesh <input.step> <output.mesh>\n");
        return 1;
    }
    try {
        return run(argv[1], argv[2]);
    } catch (const Standard_Failure& failure) {
        fprintf(stderr, "OCCT: %s\n", failure.what());
    } catch (const std::exception& failure) {
        fprintf(stderr, "%s\n", failure.what());
    } catch (...) {
        fprintf(stderr, "unknown failure\n");
    }
    return 6;
}
