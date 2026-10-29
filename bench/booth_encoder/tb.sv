`timescale 1ns/1ps
// 自检测试台：16 种输入穷举。
module tb_booth_encoder;
    // 初值设为 x：第一次赋值一定产生事件，always @* 写法在 0 时刻也会被触发（2026-10-27 修正，原来初值 0 与第一组输入相同）
    reg [2:0] bits_in = 3'bx; reg window_valid = 1'bx;
    wire [4:0] gates, cg; wire signed [2:0] digit; wire [2:0] address;
    booth_encoder dut(.bits_in(bits_in), .window_valid(window_valid), .gates(gates),
                      .complementary_gates(cg), .digit(digit), .address(address));
    integer errors = 0, i, v, d;
    reg [4:0] eg; reg [2:0] ea;
    initial begin
        for (v = 0; v < 2; v = v + 1) for (i = 0; i < 8; i = i + 1) begin
            bits_in = i; window_valid = v; #1;
            d = v ? (-2 * ((i >> 2) & 1) + ((i >> 1) & 1) + (i & 1)) : 0;
            case (d) 0: begin eg = 5'b00001; ea = 0; end
                     1: begin eg = 5'b00010; ea = 1; end
                    -1: begin eg = 5'b00100; ea = 2; end
                     2: begin eg = 5'b01000; ea = 3; end
               default: begin eg = 5'b10000; ea = 4; end endcase
            if (gates !== eg || cg !== ~eg || digit !== d[2:0] || address !== ea) begin
                errors = errors + 1;
                $display("TB_FAIL bits=%b valid=%0d expected gates=%b digit=%0d addr=%0d got gates=%b comp=%b digit=%0d addr=%0d",
                         i[2:0], v, eg, d, ea, gates, cg, digit, address);
            end
        end
        if (errors == 0) $display("TB_PASS booth_encoder: 16/16 input codes");
        else $display("TB_FAIL booth_encoder: %0d errors", errors);
        $finish;
    end
endmodule
