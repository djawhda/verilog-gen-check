`timescale 1ns/1ps
// 标准答案：lin_lookup
module lin_lookup #(
    parameter LUT_FILE = "lut_asinh_to_linear.mem"
)(
    input  wire               clk,
    input  wire signed [15:0] c,
    output reg  signed [15:0] i_lin
);
    reg [15:0] lut [0:4095];
    initial $readmemh(LUT_FILE, lut);

    // (c + 32768) >> 4：把有符号码变成偏移二进制再取高 12 位
    wire [15:0] offset = {c[15], c} + 17'd32768;
    wire [11:0] idx    = offset[15:4];

    always @(posedge clk)
        i_lin <= $signed(lut[idx]);
endmodule
