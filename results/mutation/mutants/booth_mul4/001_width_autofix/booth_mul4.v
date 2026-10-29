`timescale 1ns/1ps
// 标准答案：booth_mul4（radix-4 Booth，无乘法运算符）
module booth_mul4(
    input  wire signed [3:0] m,
    input  wire signed [3:0] q,
    output wire signed [7:0] p
);
    wire signed [7:0] m8  = $signed({{4{m[3]}}, m});   // 符号扩展到 8 位
    wire signed [7:0] m2  = m8 <<< 1;                  // 2m

    function automatic signed [7:0] pp(input [2:0] w, input signed [7:0] a1, input signed [7:0] a2);
        case (w)
            3'b001, 3'b010: pp = a1;
            3'b011:         pp = a2;
            3'b100:         pp = -a2;
            3'b101, 3'b110: pp = -a1;
            default:        pp = 8'sd0;
        endcase
    endfunction

    wire signed [6:0] pp0 = pp({q[1], q[0], 1'b0}, m8, m2);
    wire signed [7:0] pp1 = pp({q[3], q[2], q[1]}, m8, m2);
    wire signed [7:0] pp1x4 = pp1 <<< 2;                // 4·pp1
    assign p = pp0 + pp1x4;
endmodule
