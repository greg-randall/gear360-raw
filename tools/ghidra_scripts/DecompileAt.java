// Decompile functions at given addresses to C text files (headless).
// Usage (via analyzeHeadless ... -postScript DecompileAt.java OUTDIR ADDR [ADDR ...]):
//   each ADDR is hex (0x8024...); if no function exists there, one is created first.
//   An argument that doesn't start with 0x is a function name: every function whose name, or
//   namespace-qualified name (Class::method), equals it is decompiled (file name: the name with :: -> __).
//   Output: OUTDIR/<addr>.c, with the function's callers listed at the top.
// @category GearA7

import java.io.File;
import java.io.PrintWriter;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.util.ArrayList;
import java.util.List;
import ghidra.program.model.symbol.Reference;

public class DecompileAt extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) {
            printerr("usage: DecompileAt.java OUTDIR ADDR [ADDR ...]");
            return;
        }
        File outDir = new File(args[0]);
        outDir.mkdirs();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        for (int i = 1; i < args.length; i++) {
            List<Function> funcs = new ArrayList<>();
            if (args[i].startsWith("0x")) {
                Address a = toAddr(args[i]);
                Function f = getFunctionContaining(a);
                if (f == null) {
                    new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
                    f = createFunction(a, null);
                }
                if (f != null) {
                    funcs.add(f);
                }
            } else {
                FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
                while (it.hasNext()) {
                    Function g = it.next();
                    if (g.getName().equals(args[i]) || g.getName(true).equals(args[i])) {
                        funcs.add(g);
                    }
                }
            }
            if (funcs.isEmpty()) {
                printerr("no function " + args[i]);
                continue;
            }
            for (int k = 0; k < funcs.size(); k++) {
            Function f = funcs.get(k);
            String fname = args[i].replace("::", "__") + (funcs.size() > 1 ? "_" + k : "");
            println(String.format("[%d/%d] decompiling %s @ %s", i, args.length - 1, f.getName(true),
                f.getEntryPoint()));
            DecompileResults r = dec.decompileFunction(f, 120, monitor);
            try (PrintWriter w = new PrintWriter(new File(outDir, fname + ".c"))) {
                w.println("// function " + f.getName(true) + " @ " + f.getEntryPoint());
                for (Reference ref : getReferencesTo(f.getEntryPoint())) {
                    Function c = getFunctionContaining(ref.getFromAddress());
                    w.println("//   ref from " + ref.getFromAddress() + " (" + ref.getReferenceType() + ") in "
                        + (c == null ? "?" : c.getName() + " @ " + c.getEntryPoint()));
                }
                if (r.decompileCompleted()) {
                    w.println(r.getDecompiledFunction().getC());
                } else {
                    w.println("// decompile failed: " + r.getErrorMessage());
                }
            }
            }
        }
        dec.dispose();
    }
}
