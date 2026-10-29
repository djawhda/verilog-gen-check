`timescale 1ns/1ps
// 自检测试台：测试台自己读同一个表、按整数算地址，比对边界值和随机值。
module tb_lin_lookup;
    reg clk = 0; always #5 clk = ~clk;
    reg signed [15:0] c = 16'bx;
    // 输入先是 x，1 ns 后再给初值：这样 0 时刻之后一定有一次输入变化，always @* 写的组合逻辑会被触发。
    // （SystemVerilog 里声明时的初值不产生事件；如果第一组激励恰好等于初值，always @* 一次都不执行，输出一直是 x。）
    initial #1 begin c = 0; end
    wire signed [15:0] i_lin;
    lin_lookup #(.LUT_FILE("lut_asinh_to_linear.mem")) dut(.clk(clk), .c(c), .i_lin(i_lin));
    reg [15:0] ref_lut [0:4095];
    integer errors = 0, n = 0, k, idx;
    reg signed [15:0] expected;

    task automatic probe(input signed [15:0] ci);
        begin
            @(negedge clk); c = ci;
            idx = (ci + 32768) / 16;          // 整数运算：0..4095
            expected = ref_lut[idx];
            @(posedge clk); #1;
            n = n + 1;
            if (i_lin !== expected) begin
                errors = errors + 1;
                if (errors < 10) $display("TB_FAIL c=%0d idx=%0d expected %0d got %0d", ci, idx, expected, i_lin);
            end
        end
    endtask

    initial begin
        $readmemh("lut_asinh_to_linear.mem", ref_lut);
        probe(-16'sd32768); probe(-16'sd32767); probe(-16'sd17); probe(-16'sd16); probe(-16'sd1);
        probe(16'sd0); probe(16'sd15); probe(16'sd16); probe(16'sd2048); probe(-16'sd2048);
        probe(16'sd32767); probe(16'sd32752); probe(16'sd32751);
        for (k = -32768; k < 32768; k = k + 97) probe(k[15:0]);
        for (k = 0; k < 2000; k = k + 1) probe($random);
        if (errors == 0) $display("TB_PASS lin_lookup: %0d lookups", n);
        else $display("TB_FAIL lin_lookup: %0d errors", errors);
        $finish;
    end
endmodule
